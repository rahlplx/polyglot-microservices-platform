// Package services implements the core domain services for the Schema Registry.
// The RegistryService orchestrates schema registration, retrieval, listing,
// and deletion using outbound ports for persistence, compilation, validation,
// and event publishing.
// ZERO external dependencies — only stdlib, domain models, and port interfaces.
package services

import (
        "context"
        "fmt"
        "io"
        "log/slog"
        "time"

        "github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/models"
        "github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/ports/outbound"
)

// RegistryService implements all inbound use case interfaces for schema
// registration, retrieval, listing, and deletion. It is the central domain
// service that coordinates schema lifecycle management, ensuring that all
// compatibility guarantees are enforced during registration and that
// schemas are efficiently retrievable through the repository port.
type RegistryService struct {
        repo       outbound.SchemaRepository
        compiler   outbound.ProtoCompilerPort
        validator  outbound.SchemaValidatorPort
        publisher  outbound.EventPublisher
        logger     *slog.Logger
}

// NewRegistryService creates a new RegistryService with the given outbound ports.
// The logger may be nil — a default discard logger is used in that case.
// The compiler and validator may be nil — validation will be skipped if they
// are not provided, which is useful for testing or lightweight deployments.
func NewRegistryService(
        repo outbound.SchemaRepository,
        compiler outbound.ProtoCompilerPort,
        validator outbound.SchemaValidatorPort,
        publisher outbound.EventPublisher,
        logger *slog.Logger,
) *RegistryService {
        if logger == nil {
                logger = slog.New(slog.NewTextHandler(io.Discard, nil))
        }
        return &RegistryService{
                repo:      repo,
                compiler:  compiler,
                validator: validator,
                publisher: publisher,
                logger:    logger,
        }
}

// --- RegisterSchemaUseCase implementation ---

// Register validates and registers a new schema version under the given subject.
// The registration process follows these steps:
//  1. Compute the fingerprint of the schema definition for deduplication.
//  2. Check if an identical schema already exists (fingerprint match).
//  3. Validate the schema for syntax correctness using the compiler.
//  4. Determine the next version number for the subject.
//  5. Check compatibility against the latest version if compatibility is not NONE.
//  6. Persist the schema record.
//  7. Publish a schema-registered event.
//
// If the schema is incompatible with the latest version, a SchemaIncompatibleError
// is returned with detailed violation information.
func (s *RegistryService) Register(ctx context.Context, req models.RegisterSchemaRequest) (models.RegisterSchemaResponse, error) {
        s.logger.Debug("registering schema",
                slog.String("subject", req.Subject),
                slog.String("type", req.Type.String()),
                slog.Int("definition_len", len(req.Definition)),
        )

        // Step 1: Create a preliminary schema object and compute fingerprint
        schema := models.Schema{
                Subject:          req.Subject,
                Type:             req.Type,
                Definition:       req.Definition,
                References:       req.References,
                Description:      req.Description,
                RegisteredBy:     req.RegisteredBy,
                RegisteredAt:     time.Now().UTC(),
                Deprecated:       false,
        }
        schema.Fingerprint = schema.ComputeFingerprint()

        // Step 2: Check for duplicate by fingerprint
        existing, err := s.repo.FindByFingerprint(ctx, req.Subject, schema.Fingerprint)
        if err != nil {
                s.logger.Warn("fingerprint lookup failed, continuing with registration",
                        slog.String("subject", req.Subject),
                        slog.String("error", err.Error()),
                )
        }
        if existing != nil {
                s.logger.Info("schema with identical fingerprint already exists",
                        slog.String("subject", req.Subject),
                        slog.Int("existing_version", int(existing.Version)),
                        slog.String("fingerprint", schema.Fingerprint),
                )
                return models.RegisterSchemaResponse{
                        SchemaID:     existing.ID,
                        Version:      existing.Version,
                        Fingerprint:  existing.Fingerprint,
                        RegisteredAt: existing.RegisteredAt,
                        CompatibilityCheck: models.CompatibilityResult{
                                Compatible:       true,
                                CompatibilityLvl: existing.CompatibilityLvl,
                        },
                }, nil
        }

        // Step 3: Validate schema syntax using the compiler (if available)
        if s.compiler != nil && req.Type == models.SchemaTypeProtobuf {
                result, err := s.compiler.Compile(ctx, req.Definition, nil)
                if err != nil {
                        return models.RegisterSchemaResponse{}, fmt.Errorf("schema compilation failed: %w", err)
                }
                if !result.Success {
                        return models.RegisterSchemaResponse{}, &InvalidSchemaError{
                                Subject: req.Subject,
                                Errors:  result.Errors,
                        }
                }
        }

        // Step 4: Determine compatibility level
        compatLevel := models.CompatibilityBackward // default
        if req.CompatibilityLvl != nil {
                compatLevel = *req.CompatibilityLvl
        }
        schema.CompatibilityLvl = compatLevel

        // Step 5: Check compatibility against the latest version
        var compatResult models.CompatibilityResult
        if compatLevel != models.CompatibilityNone && s.validator != nil {
                latest, err := s.repo.FindLatestBySubject(ctx, req.Subject)
                if err != nil {
                        s.logger.Warn("failed to find latest version for compatibility check",
                                slog.String("subject", req.Subject),
                                slog.String("error", err.Error()),
                        )
                }
                if latest != nil {
                        compatResult, err = s.checkCompatibility(ctx, latest.Definition, req.Definition, compatLevel)
                        if err != nil {
                                return models.RegisterSchemaResponse{}, fmt.Errorf("compatibility check failed: %w", err)
                        }
                        if !compatResult.Compatible {
                                return models.RegisterSchemaResponse{}, &SchemaIncompatibleError{
                                        Subject:    req.Subject,
                                        Violations: compatResult.Violations,
                                        Level:      compatLevel,
                                }
                        }
                }
        } else {
                compatResult = models.CompatibilityResult{
                        Compatible:       true,
                        CompatibilityLvl: compatLevel,
                }
        }

        // Step 6: Determine next version number
        nextVersion, err := s.repo.GetNextVersion(ctx, req.Subject)
        if err != nil {
                return models.RegisterSchemaResponse{}, fmt.Errorf("failed to determine next version for subject %q: %w", req.Subject, err)
        }
        schema.Version = nextVersion

        // Step 7: Persist the schema
        saved, err := s.repo.Save(ctx, schema)
        if err != nil {
                return models.RegisterSchemaResponse{}, fmt.Errorf("failed to save schema for subject %q: %w", req.Subject, err)
        }

        s.logger.Info("schema registered",
                slog.String("subject", req.Subject),
                slog.Int("schema_id", int(saved.ID)),
                slog.Int("version", int(saved.Version)),
                slog.String("fingerprint", saved.Fingerprint),
                slog.String("compatibility", compatLevel.String()),
        )

        // Step 8: Publish event (non-blocking)
        if s.publisher != nil {
                if err := s.publisher.PublishSchemaRegistered(ctx, saved, compatResult); err != nil {
                        s.logger.Warn("failed to publish schema-registered event",
                                slog.String("subject", req.Subject),
                                slog.String("error", err.Error()),
                        )
                }
        }

        return models.RegisterSchemaResponse{
                SchemaID:         saved.ID,
                Version:          saved.Version,
                Fingerprint:      saved.Fingerprint,
                RegisteredAt:     saved.RegisteredAt,
                CompatibilityCheck: compatResult,
        }, nil
}

// --- GetSchemaUseCase implementation ---

// Get retrieves a schema by subject and version, or by global schema ID.
// When version is nil, it returns the latest version for the subject.
// When includeReferences is true, it recursively resolves all schema
// dependencies and includes their definitions in the response.
func (s *RegistryService) Get(ctx context.Context, req models.GetSchemaRequest) (models.GetSchemaResponse, error) {
        var schema *models.Schema
        var err error

        switch {
        case req.SchemaID != nil:
                schema, err = s.repo.FindById(ctx, *req.SchemaID)
                if err != nil {
                        return models.GetSchemaResponse{}, fmt.Errorf("failed to find schema by ID %d: %w", *req.SchemaID, err)
                }
        case req.Subject != "":
                if req.Version != nil {
                        schema, err = s.repo.FindBySubjectAndVersion(ctx, req.Subject, *req.Version)
                        if err != nil {
                                return models.GetSchemaResponse{}, fmt.Errorf("failed to find schema %q version %d: %w", req.Subject, *req.Version, err)
                        }
                } else {
                        schema, err = s.repo.FindLatestBySubject(ctx, req.Subject)
                        if err != nil {
                                return models.GetSchemaResponse{}, fmt.Errorf("failed to find latest schema for subject %q: %w", req.Subject, err)
                        }
                }
        default:
                return models.GetSchemaResponse{}, fmt.Errorf("either subject or schema_id must be provided")
        }

        if schema == nil {
                return models.GetSchemaResponse{}, &SchemaNotFoundError{
                        Subject: req.Subject,
                }
        }

        // Skip deprecated versions unless explicitly requested
        if schema.Deprecated && !req.IncludeDeprecated {
                return models.GetSchemaResponse{}, &SchemaNotFoundError{
                        Subject: req.Subject,
                        Version: req.Version,
                }
        }

        // Resolve references if requested
        if req.IncludeReferences && len(schema.References) > 0 {
                resolved, err := s.resolveReferences(ctx, schema.References)
                if err != nil {
                        s.logger.Warn("failed to resolve schema references",
                                slog.String("subject", schema.Subject),
                                slog.String("error", err.Error()),
                        )
                } else {
                        schema.References = resolved
                }
        }

        return models.GetSchemaResponse{Schema: *schema}, nil
}

// --- ListSchemasUseCase implementation ---

// List returns a paginated list of schema subjects matching the filter criteria.
// It uses cursor-based pagination with opaque page tokens for consistent
// results across pages.
func (s *RegistryService) List(ctx context.Context, req models.ListSchemasRequest) (models.ListSchemasResponse, error) {
        if req.PageSize <= 0 {
                req.PageSize = 20
        }
        if req.PageSize > 100 {
                req.PageSize = 100
        }

        subjects, err := s.repo.ListSubjects(ctx, req.Prefix)
        if err != nil {
                return models.ListSchemasResponse{}, fmt.Errorf("failed to list subjects: %w", err)
        }

        totalCount, err := s.repo.CountSubjects(ctx, req.Prefix)
        if err != nil {
                return models.ListSchemasResponse{}, fmt.Errorf("failed to count subjects: %w", err)
        }

        // Build subject summaries
        var summaries []models.SubjectInfo
        for _, subject := range subjects {
                latest, err := s.repo.FindLatestBySubject(ctx, subject)
                if err != nil {
                        s.logger.Warn("failed to get latest version for subject",
                                slog.String("subject", subject),
                                slog.String("error", err.Error()),
                        )
                        continue
                }
                if latest == nil {
                        continue
                }

                // Skip deprecated subjects unless requested
                if latest.Deprecated && !req.IncludeDeprecated {
                        continue
                }

                // Filter by schema type if specified
                if req.Type != nil && latest.Type != *req.Type {
                        continue
                }

                versions, err := s.repo.FindBySubject(ctx, subject)
                if err != nil {
                        s.logger.Warn("failed to count versions for subject",
                                slog.String("subject", subject),
                                slog.String("error", err.Error()),
                        )
                        continue
                }

                summaries = append(summaries, models.SubjectInfo{
                        Name:             subject,
                        CompatibilityLvl: latest.CompatibilityLvl,
                        LatestVersion:    latest.Version,
                        Type:             latest.Type,
                        TotalVersions:    int32(len(versions)),
                        Deprecated:       latest.Deprecated,
                        RegisteredAt:     latest.RegisteredAt,
                        Description:      latest.Description,
                })
        }

        // Apply pagination
        start := 0
        if req.PageToken != "" {
                // Simple token parsing: token is the subject name to start after
                for i, sum := range summaries {
                        if sum.Name == req.PageToken {
                                start = i + 1
                                break
                        }
                }
        }

        end := start + int(req.PageSize)
        if end > len(summaries) {
                end = len(summaries)
        }

        var nextPageToken string
        if end < len(summaries) {
                nextPageToken = summaries[end-1].Name
        }

        return models.ListSchemasResponse{
                Subjects:      summaries[start:end],
                TotalCount:    totalCount,
                NextPageToken: nextPageToken,
        }, nil
}

// --- DeleteSubjectUseCase implementation ---

// Delete removes a subject and all its versions. If permanent is true,
// the data is physically removed; otherwise it is soft-deleted.
func (s *RegistryService) Delete(ctx context.Context, req models.DeleteSubjectRequest) error {
        s.logger.Info("deleting subject",
                slog.String("subject", req.Subject),
                slog.Bool("permanent", req.Permanent),
                slog.String("deleted_by", req.DeletedBy),
        )

        if err := s.repo.DeleteSubject(ctx, req.Subject, req.Permanent); err != nil {
                return fmt.Errorf("failed to delete subject %q: %w", req.Subject, err)
        }

        s.logger.Info("subject deleted",
                slog.String("subject", req.Subject),
                slog.Bool("permanent", req.Permanent),
        )

        return nil
}

// --- Helper methods ---

// checkCompatibility performs a compatibility check between two schema definitions.
// It uses the validator port to perform the actual check and wraps the result
// with the specified compatibility level.
func (s *RegistryService) checkCompatibility(ctx context.Context, previousDef, proposedDef string, level models.CompatibilityLevel) (models.CompatibilityResult, error) {
        checkLevel := models.CheckLevelDefault
        if level.IsTransitive() {
                checkLevel = models.CheckLevelStrict
        }

        breakingResp, err := s.validator.CheckBreaking(ctx, previousDef, proposedDef, checkLevel)
        if err != nil {
                return models.CompatibilityResult{}, fmt.Errorf("breaking change check failed: %w", err)
        }

        violations := make([]models.CompatibilityViolation, 0, len(breakingResp.Changes))
        for _, change := range breakingResp.Changes {
                violations = append(violations, models.CompatibilityViolation{
                        Description:  change.Description,
                        FieldPath:    change.FieldPath,
                        Rule:         change.ChangeType,
                        PreviousType: change.Category,
                })
        }

        compatible := !breakingResp.HasBreakingChanges

        // Adjust compatibility based on the level
        if level.IsForward() && compatible {
                // Forward compatibility also requires checking in the reverse direction
                reverseResp, err := s.validator.CheckBreaking(ctx, proposedDef, previousDef, checkLevel)
                if err != nil {
                        s.logger.Warn("reverse compatibility check failed",
                                slog.String("error", err.Error()),
                        )
                } else if reverseResp.HasBreakingChanges {
                        compatible = false
                        for _, change := range reverseResp.Changes {
                                violations = append(violations, models.CompatibilityViolation{
                                        Description:  "forward compatibility: " + change.Description,
                                        FieldPath:    change.FieldPath,
                                        Rule:         change.ChangeType,
                                        PreviousType: change.Category,
                                })
                        }
                }
        }

        return models.CompatibilityResult{
                Compatible:       compatible,
                Violations:       violations,
                CompatibilityLvl: level,
        }, nil
}

// resolveReferences recursively resolves schema references, fetching each
// referenced schema from the repository and building a complete dependency tree.
func (s *RegistryService) resolveReferences(ctx context.Context, refs []models.SchemaReference) ([]models.SchemaReference, error) {
        resolved := make([]models.SchemaReference, 0, len(refs))
        for _, ref := range refs {
                schema, err := s.repo.FindBySubjectAndVersion(ctx, ref.Subject, ref.Version)
                if err != nil {
                        return nil, fmt.Errorf("failed to resolve reference %q version %d: %w", ref.Subject, ref.Version, err)
                }
                if schema == nil {
                        continue
                }
                resolved = append(resolved, ref)

                // Recursively resolve nested references
                if len(schema.References) > 0 {
                        nested, err := s.resolveReferences(ctx, schema.References)
                        if err != nil {
                                return nil, err
                        }
                        resolved = append(resolved, nested...)
                }
        }
        return resolved, nil
}

// --- Domain Errors ---

// SchemaIncompatibleError is returned when a proposed schema violates the
// compatibility rules configured for the subject.
type SchemaIncompatibleError struct {
        Subject    string
        Violations []models.CompatibilityViolation
        Level      models.CompatibilityLevel
}

func (e *SchemaIncompatibleError) Error() string {
        return fmt.Sprintf("schema for subject %q is incompatible at %s level: %d violation(s) detected",
                e.Subject, e.Level, len(e.Violations))
}

// InvalidSchemaError is returned when a schema definition fails syntax
// validation and cannot be parsed.
type InvalidSchemaError struct {
        Subject string
        Errors  []models.ValidationError
}

func (e *InvalidSchemaError) Error() string {
        return fmt.Sprintf("schema for subject %q is invalid: %d error(s) found",
                e.Subject, len(e.Errors))
}

// SchemaNotFoundError is returned when a requested schema does not exist.
type SchemaNotFoundError struct {
        Subject string
        Version *int32
}

func (e *SchemaNotFoundError) Error() string {
        if e.Version != nil {
                return fmt.Sprintf("schema not found: subject %q version %d", e.Subject, *e.Version)
        }
        return fmt.Sprintf("schema not found: subject %q", e.Subject)
}

// DuplicateSchemaError is returned when an identical schema already exists.
type DuplicateSchemaError struct {
        Subject     string
        Version     int32
        Fingerprint string
}

func (e *DuplicateSchemaError) Error() string {
        return fmt.Sprintf("duplicate schema: subject %q already has version %d with fingerprint %s",
                e.Subject, e.Version, e.Fingerprint)
}
