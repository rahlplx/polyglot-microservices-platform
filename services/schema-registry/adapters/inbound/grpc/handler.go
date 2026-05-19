// Package grpc implements the inbound gRPC adapter for the Schema Registry service.
// It translates gRPC requests into domain-level use case calls and domain
// responses back into gRPC responses. The handler implements the
// SchemaRegistryService proto definition with Register, Get, Validate,
// CheckBreaking, and List RPC methods.
package grpc

import (
        "context"
        "log/slog"

        "google.golang.org/grpc"
        "google.golang.org/grpc/codes"
        "google.golang.org/grpc/status"

        "github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/models"
        "github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/ports/inbound"
        "github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/services"
)

// Proto-generated types would normally come from the api/proto directory.
// For this implementation, we define the message types inline to avoid
// requiring the protoc toolchain at development time. In production,
// these would be generated from schemaregistry.proto via `buf generate`.

// RegisterSchemaRequest is the gRPC request message for schema registration.
type RegisterSchemaRequest struct {
        Subject           string               `json:"subject,omitempty"`
        SchemaType        string               `json:"schema_type,omitempty"`
        SchemaDefinition  string               `json:"schema_definition,omitempty"`
        References        []*SchemaReferenceMsg `json:"references,omitempty"`
        CompatibilityLevel string              `json:"compatibility_level,omitempty"`
        Description       string               `json:"description,omitempty"`
}

// RegisterSchemaResponse is the gRPC response message for schema registration.
type RegisterSchemaResponse struct {
        SchemaID     int32                  `json:"schema_id,omitempty"`
        Version      int32                  `json:"version,omitempty"`
        Fingerprint  string                 `json:"fingerprint,omitempty"`
        RegisteredAt int64                  `json:"registered_at,omitempty"` // Unix timestamp
        CompatibilityCheck *CompatibilityResultMsg `json:"compatibility_check,omitempty"`
}

// GetSchemaRequest is the gRPC request message for schema retrieval.
type GetSchemaRequest struct {
        Subject           string `json:"subject,omitempty"`
        Version           *int32 `json:"version,omitempty"`
        SchemaID          *int32 `json:"schema_id,omitempty"`
        IncludeReferences bool   `json:"include_references,omitempty"`
        IncludeDeprecated bool   `json:"include_deprecated,omitempty"`
}

// GetSchemaResponse is the gRPC response message for schema retrieval.
type GetSchemaResponse struct {
        SchemaID         int32                 `json:"schema_id,omitempty"`
        Version          int32                 `json:"version,omitempty"`
        Subject          string                `json:"subject,omitempty"`
        SchemaType       string                `json:"schema_type,omitempty"`
        SchemaDefinition string                `json:"schema_definition,omitempty"`
        References       []*SchemaReferenceMsg `json:"references,omitempty"`
        Fingerprint      string                `json:"fingerprint,omitempty"`
        RegisteredAt     int64                 `json:"registered_at,omitempty"`
        Deprecated       bool                  `json:"deprecated,omitempty"`
        Description      string                `json:"description,omitempty"`
}

// ValidateSchemaRequest is the gRPC request message for schema validation.
type ValidateSchemaRequest struct {
        Subject        string `json:"subject,omitempty"`
        SchemaDefinition string `json:"schema_definition,omitempty"`
        SchemaType     string `json:"schema_type,omitempty"`
        ValidationLevel string `json:"validation_level,omitempty"`
        TargetVersion  *int32 `json:"target_version,omitempty"`
}

// ValidateSchemaResponse is the gRPC response message for schema validation.
type ValidateSchemaResponse struct {
        Valid              bool                    `json:"valid,omitempty"`
        Errors             []*ValidationErrorMsg   `json:"errors,omitempty"`
        Warnings           []*ValidationWarningMsg `json:"warnings,omitempty"`
        CompatibilityResult *CompatibilityResultMsg `json:"compatibility_result,omitempty"`
}

// CheckBreakingRequest is the gRPC request message for breaking change detection.
type CheckBreakingRequest struct {
        Subject         string `json:"subject,omitempty"`
        PreviousVersion *int32 `json:"previous_version,omitempty"`
        ProposedSchema  string `json:"proposed_schema,omitempty"`
        CheckLevel      string `json:"check_level,omitempty"`
}

// CheckBreakingResponse is the gRPC response message for breaking change detection.
type CheckBreakingResponse struct {
        HasBreakingChanges bool                       `json:"has_breaking_changes,omitempty"`
        Changes            []*BreakingChangeMsg       `json:"changes,omitempty"`
        Severity           string                     `json:"severity,omitempty"`
        Mitigations        []*MitigationSuggestionMsg `json:"mitigations,omitempty"`
}

// ListSchemasRequest is the gRPC request message for schema listing.
type ListSchemasRequest struct {
        Prefix            string `json:"prefix,omitempty"`
        SchemaType        string `json:"schema_type,omitempty"`
        IncludeDeprecated bool   `json:"include_deprecated,omitempty"`
        PageSize          int32  `json:"page_size,omitempty"`
        PageToken         string `json:"page_token,omitempty"`
}

// ListSchemasResponse is the gRPC response message for schema listing.
type ListSchemasResponse struct {
        Subjects      []*SubjectSummaryMsg `json:"subjects,omitempty"`
        TotalCount    int64                `json:"total_count,omitempty"`
        NextPageToken string               `json:"next_page_token,omitempty"`
}

// SchemaReferenceMsg represents a schema reference in gRPC messages.
type SchemaReferenceMsg struct {
        Name    string `json:"name,omitempty"`
        Subject string `json:"subject,omitempty"`
        Version int32  `json:"version,omitempty"`
}

// CompatibilityResultMsg represents a compatibility check result in gRPC messages.
type CompatibilityResultMsg struct {
        Compatible       bool                        `json:"compatible,omitempty"`
        Violations       []*CompatibilityViolationMsg `json:"violations,omitempty"`
        CompatibilityLevel string                     `json:"compatibility_level,omitempty"`
}

// CompatibilityViolationMsg represents a compatibility violation in gRPC messages.
type CompatibilityViolationMsg struct {
        Description  string `json:"description,omitempty"`
        FieldPath    string `json:"field_path,omitempty"`
        Rule         string `json:"rule,omitempty"`
        PreviousType string `json:"previous_type,omitempty"`
        ProposedType string `json:"proposed_type,omitempty"`
}

// ValidationErrorMsg represents a validation error in gRPC messages.
type ValidationErrorMsg struct {
        Message  string `json:"message,omitempty"`
        Location string `json:"location,omitempty"`
        RuleID   string `json:"rule_id,omitempty"`
}

// ValidationWarningMsg represents a validation warning in gRPC messages.
type ValidationWarningMsg struct {
        Message  string `json:"message,omitempty"`
        Location string `json:"location,omitempty"`
        RuleID   string `json:"rule_id,omitempty"`
}

// BreakingChangeMsg represents a breaking change in gRPC messages.
type BreakingChangeMsg struct {
        ChangeType  string `json:"change_type,omitempty"`
        FieldPath   string `json:"field_path,omitempty"`
        Description string `json:"description,omitempty"`
        Category    string `json:"category,omitempty"`
}

// MitigationSuggestionMsg represents a mitigation suggestion in gRPC messages.
type MitigationSuggestionMsg struct {
        ChangeType string `json:"change_type,omitempty"`
        Suggestion string `json:"suggestion,omitempty"`
        Example    string `json:"example,omitempty"`
}

// SubjectSummaryMsg represents a subject summary in gRPC messages.
type SubjectSummaryMsg struct {
        Name              string `json:"name,omitempty"`
        CompatibilityLevel string `json:"compatibility_level,omitempty"`
        LatestVersion     int32  `json:"latest_version,omitempty"`
        SchemaType        string `json:"schema_type,omitempty"`
        TotalVersions     int32  `json:"total_versions,omitempty"`
        Deprecated        bool   `json:"deprecated,omitempty"`
        RegisteredAt      int64  `json:"registered_at,omitempty"`
        Description       string `json:"description,omitempty"`
}

// SchemaRegistryServiceServer is the gRPC service interface.
type SchemaRegistryServiceServer interface {
        Register(context.Context, *RegisterSchemaRequest) (*RegisterSchemaResponse, error)
        Get(context.Context, *GetSchemaRequest) (*GetSchemaResponse, error)
        Validate(context.Context, *ValidateSchemaRequest) (*ValidateSchemaResponse, error)
        CheckBreaking(context.Context, *CheckBreakingRequest) (*CheckBreakingResponse, error)
        List(context.Context, *ListSchemasRequest) (*ListSchemasResponse, error)
}

// Handler implements the SchemaRegistryServiceServer gRPC interface by delegating
// to the domain use case interfaces.
type Handler struct {
        register      inbound.RegisterSchemaUseCase
        get           inbound.GetSchemaUseCase
        list          inbound.ListSchemasUseCase
        validate      inbound.ValidateSchemaUseCase
        checkBreaking inbound.CheckBreakingUseCase
        logger        *slog.Logger
}

// NewHandler creates a new gRPC handler with the given use case dependencies.
func NewHandler(
        register inbound.RegisterSchemaUseCase,
        get inbound.GetSchemaUseCase,
        list inbound.ListSchemasUseCase,
        validate inbound.ValidateSchemaUseCase,
        checkBreaking inbound.CheckBreakingUseCase,
        logger *slog.Logger,
) *Handler {
        if logger == nil {
                logger = slog.Default()
        }
        return &Handler{
                register:      register,
                get:           get,
                list:          list,
                validate:      validate,
                checkBreaking: checkBreaking,
                logger:        logger,
        }
}

// RegisterServer registers the handler with a gRPC server.
func (h *Handler) RegisterServer(srv *grpc.Server) {
        // In production with generated proto stubs, this would call:
        // RegisterSchemaRegistryServiceServer(srv, h)
        h.logger.Info("gRPC handler registered on server")
}

// Register handles incoming gRPC Register requests.
func (h *Handler) Register(ctx context.Context, req *RegisterSchemaRequest) (*RegisterSchemaResponse, error) {
        h.logger.Debug("gRPC Register called",
                slog.String("subject", req.Subject),
                slog.String("type", req.SchemaType),
        )

        schemaType, err := models.ParseSchemaType(req.SchemaType)
        if err != nil {
                return nil, status.Errorf(codes.InvalidArgument, "invalid schema type: %v", err)
        }

        var compatLvl *models.CompatibilityLevel
        if req.CompatibilityLevel != "" {
                level, err := models.ParseCompatibilityLevel(req.CompatibilityLevel)
                if err != nil {
                        return nil, status.Errorf(codes.InvalidArgument, "invalid compatibility level: %v", err)
                }
                compatLvl = &level
        }

        refs := make([]models.SchemaReference, 0, len(req.References))
        for _, r := range req.References {
                refs = append(refs, models.SchemaReference{
                        Name:    r.Name,
                        Subject: r.Subject,
                        Version: r.Version,
                })
        }

        resp, err := h.register.Register(ctx, models.RegisterSchemaRequest{
                Subject:          req.Subject,
                Type:             schemaType,
                Definition:       req.SchemaDefinition,
                References:       refs,
                CompatibilityLvl: compatLvl,
                Description:      req.Description,
        })
        if err != nil {
                return nil, h.mapError(err)
        }

        return &RegisterSchemaResponse{
                SchemaID:     resp.SchemaID,
                Version:      resp.Version,
                Fingerprint:  resp.Fingerprint,
                RegisteredAt: resp.RegisteredAt.Unix(),
                CompatibilityCheck: convertCompatibilityResult(resp.CompatibilityCheck),
        }, nil
}

// Get handles incoming gRPC Get requests.
func (h *Handler) Get(ctx context.Context, req *GetSchemaRequest) (*GetSchemaResponse, error) {
        h.logger.Debug("gRPC Get called",
                slog.String("subject", req.Subject),
        )

        resp, err := h.get.Get(ctx, models.GetSchemaRequest{
                Subject:           req.Subject,
                Version:           req.Version,
                SchemaID:          req.SchemaID,
                IncludeReferences: req.IncludeReferences,
                IncludeDeprecated: req.IncludeDeprecated,
        })
        if err != nil {
                return nil, h.mapError(err)
        }

        schema := resp.Schema
        return &GetSchemaResponse{
                SchemaID:         schema.ID,
                Version:          schema.Version,
                Subject:          schema.Subject,
                SchemaType:       schema.Type.String(),
                SchemaDefinition: schema.Definition,
                References:       convertSchemaReferences(schema.References),
                Fingerprint:      schema.Fingerprint,
                RegisteredAt:     schema.RegisteredAt.Unix(),
                Deprecated:       schema.Deprecated,
                Description:      schema.Description,
        }, nil
}

// Validate handles incoming gRPC Validate requests.
func (h *Handler) Validate(ctx context.Context, req *ValidateSchemaRequest) (*ValidateSchemaResponse, error) {
        h.logger.Debug("gRPC Validate called",
                slog.String("subject", req.Subject),
                slog.String("level", req.ValidationLevel),
        )

        schemaType, err := models.ParseSchemaType(req.SchemaType)
        if err != nil {
                return nil, status.Errorf(codes.InvalidArgument, "invalid schema type: %v", err)
        }

        validationLvl, err := models.ParseValidationLevel(req.ValidationLevel)
        if err != nil {
                return nil, status.Errorf(codes.InvalidArgument, "invalid validation level: %v", err)
        }

        resp, err := h.validate.Validate(ctx, models.ValidateSchemaRequest{
                Subject:       req.Subject,
                Definition:    req.SchemaDefinition,
                Type:          schemaType,
                ValidationLvl: validationLvl,
                TargetVersion: req.TargetVersion,
        })
        if err != nil {
                return nil, h.mapError(err)
        }

        var compatResult *CompatibilityResultMsg
        if resp.CompatibilityResult != nil {
                cr := convertCompatibilityResult(*resp.CompatibilityResult)
                compatResult = &cr
        }

        return &ValidateSchemaResponse{
                Valid:              resp.Valid,
                Errors:             convertValidationErrors(resp.Errors),
                Warnings:           convertValidationWarnings(resp.Warnings),
                CompatibilityResult: compatResult,
        }, nil
}

// CheckBreaking handles incoming gRPC CheckBreaking requests.
func (h *Handler) CheckBreaking(ctx context.Context, req *CheckBreakingRequest) (*CheckBreakingResponse, error) {
        h.logger.Debug("gRPC CheckBreaking called",
                slog.String("subject", req.Subject),
        )

        checkLevel, err := models.ParseCheckLevel(req.CheckLevel)
        if err != nil {
                return nil, status.Errorf(codes.InvalidArgument, "invalid check level: %v", err)
        }

        resp, err := h.checkBreaking.CheckBreaking(ctx, models.CheckBreakingRequest{
                Subject:         req.Subject,
                PreviousVersion: req.PreviousVersion,
                ProposedSchema:  req.ProposedSchema,
                CheckLevel:      checkLevel,
        })
        if err != nil {
                return nil, h.mapError(err)
        }

        return &CheckBreakingResponse{
                HasBreakingChanges: resp.HasBreakingChanges,
                Changes:            convertBreakingChanges(resp.Changes),
                Severity:           resp.Severity,
                Mitigations:        convertMitigations(resp.Mitigations),
        }, nil
}

// List handles incoming gRPC List requests.
func (h *Handler) List(ctx context.Context, req *ListSchemasRequest) (*ListSchemasResponse, error) {
        h.logger.Debug("gRPC List called",
                slog.String("prefix", req.Prefix),
                slog.Int32("page_size", req.PageSize),
        )

        var schemaType *models.SchemaType
        if req.SchemaType != "" {
                st, err := models.ParseSchemaType(req.SchemaType)
                if err != nil {
                        return nil, status.Errorf(codes.InvalidArgument, "invalid schema type: %v", err)
                }
                schemaType = &st
        }

        resp, err := h.list.List(ctx, models.ListSchemasRequest{
                Prefix:            req.Prefix,
                Type:              schemaType,
                IncludeDeprecated: req.IncludeDeprecated,
                PageSize:          req.PageSize,
                PageToken:         req.PageToken,
        })
        if err != nil {
                return nil, h.mapError(err)
        }

        return &ListSchemasResponse{
                Subjects:      convertSubjectSummaries(resp.Subjects),
                TotalCount:    resp.TotalCount,
                NextPageToken: resp.NextPageToken,
        }, nil
}

// --- Conversion helpers ---

func convertSchemaReferences(refs []models.SchemaReference) []*SchemaReferenceMsg {
        result := make([]*SchemaReferenceMsg, 0, len(refs))
        for _, r := range refs {
                result = append(result, &SchemaReferenceMsg{
                        Name:    r.Name,
                        Subject: r.Subject,
                        Version: r.Version,
                })
        }
        return result
}

func convertCompatibilityResult(cr models.CompatibilityResult) *CompatibilityResultMsg {
        violations := make([]*CompatibilityViolationMsg, 0, len(cr.Violations))
        for _, v := range cr.Violations {
                violations = append(violations, &CompatibilityViolationMsg{
                        Description:  v.Description,
                        FieldPath:    v.FieldPath,
                        Rule:         v.Rule,
                        PreviousType: v.PreviousType,
                        ProposedType: v.ProposedType,
                })
        }
        return &CompatibilityResultMsg{
                Compatible:         cr.Compatible,
                Violations:         violations,
                CompatibilityLevel: cr.CompatibilityLvl.String(),
        }
}

func convertValidationErrors(errs []models.ValidationError) []*ValidationErrorMsg {
        result := make([]*ValidationErrorMsg, 0, len(errs))
        for _, e := range errs {
                result = append(result, &ValidationErrorMsg{
                        Message:  e.Message,
                        Location: e.Location,
                        RuleID:   e.RuleID,
                })
        }
        return result
}

func convertValidationWarnings(warnings []models.ValidationWarning) []*ValidationWarningMsg {
        result := make([]*ValidationWarningMsg, 0, len(warnings))
        for _, w := range warnings {
                result = append(result, &ValidationWarningMsg{
                        Message:  w.Message,
                        Location: w.Location,
                        RuleID:   w.RuleID,
                })
        }
        return result
}

func convertBreakingChanges(changes []models.BreakingChange) []*BreakingChangeMsg {
        result := make([]*BreakingChangeMsg, 0, len(changes))
        for _, c := range changes {
                result = append(result, &BreakingChangeMsg{
                        ChangeType:  c.ChangeType,
                        FieldPath:   c.FieldPath,
                        Description: c.Description,
                        Category:    c.Category,
                })
        }
        return result
}

func convertMitigations(mitigations []models.MitigationSuggestion) []*MitigationSuggestionMsg {
        result := make([]*MitigationSuggestionMsg, 0, len(mitigations))
        for _, m := range mitigations {
                result = append(result, &MitigationSuggestionMsg{
                        ChangeType: m.ChangeType,
                        Suggestion: m.Suggestion,
                        Example:    m.Example,
                })
        }
        return result
}

func convertSubjectSummaries(summaries []models.SubjectInfo) []*SubjectSummaryMsg {
        result := make([]*SubjectSummaryMsg, 0, len(summaries))
        for _, s := range summaries {
                result = append(result, &SubjectSummaryMsg{
                        Name:               s.Name,
                        CompatibilityLevel: s.CompatibilityLvl.String(),
                        LatestVersion:      s.LatestVersion,
                        SchemaType:         s.Type.String(),
                        TotalVersions:      s.TotalVersions,
                        Deprecated:         s.Deprecated,
                        RegisteredAt:       s.RegisteredAt.Unix(),
                        Description:        s.Description,
                })
        }
        return result
}

// mapError converts domain errors to appropriate gRPC status codes.
func (h *Handler) mapError(err error) error {
        switch e := err.(type) {
        case *services.SchemaIncompatibleError:
                return status.Errorf(codes.InvalidArgument,
                        "schema incompatible for subject %q: %d violation(s) detected",
                        e.Subject, len(e.Violations))
        case *services.InvalidSchemaError:
                return status.Errorf(codes.InvalidArgument,
                        "invalid schema for subject %q: %d error(s)",
                        e.Subject, len(e.Errors))
        case *services.SchemaNotFoundError:
                return status.Errorf(codes.NotFound, "%v", e)
        case *services.DuplicateSchemaError:
                return status.Errorf(codes.AlreadyExists, "%v", e)
        default:
                return status.Errorf(codes.Internal, "internal error: %v", err)
        }
}

// Ensure Handler implements SchemaRegistryServiceServer at compile time.
var _ SchemaRegistryServiceServer = (*Handler)(nil)

