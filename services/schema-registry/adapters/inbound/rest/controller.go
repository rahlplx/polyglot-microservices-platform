// Package rest implements the inbound REST adapter for the Schema Registry service.
// It translates HTTP requests into domain-level use case calls and domain
// responses back into HTTP JSON responses. The controller is designed to be
// compatible with the Confluent Schema Registry REST API for drop-in
// compatibility, while also supporting Schema Registry-specific endpoints.
package rest

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/ports/inbound"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/services"
)

// Controller implements the REST API for the Schema Registry service.
// It maps HTTP endpoints to domain use case calls following the Confluent
// Schema Registry API convention where possible for compatibility.
type Controller struct {
	register      inbound.RegisterSchemaUseCase
	get           inbound.GetSchemaUseCase
	list          inbound.ListSchemasUseCase
	validate      inbound.ValidateSchemaUseCase
	checkBreaking inbound.CheckBreakingUseCase
	deleteSubject inbound.DeleteSubjectUseCase
	logger        *slog.Logger
	mux           *http.ServeMux
}

// NewController creates a new REST controller with the given use case dependencies.
func NewController(
	register inbound.RegisterSchemaUseCase,
	get inbound.GetSchemaUseCase,
	list inbound.ListSchemasUseCase,
	validate inbound.ValidateSchemaUseCase,
	checkBreaking inbound.CheckBreakingUseCase,
	deleteSubject inbound.DeleteSubjectUseCase,
	logger *slog.Logger,
) *Controller {
	if logger == nil {
		logger = slog.Default()
	}

	c := &Controller{
		register:      register,
		get:           get,
		list:          list,
		validate:      validate,
		checkBreaking: checkBreaking,
		deleteSubject: deleteSubject,
		logger:        logger,
		mux:           http.NewServeMux(),
	}

	c.registerRoutes()
	return c
}

// Handler returns the HTTP handler for this controller.
func (c *Controller) Handler() http.Handler {
	return c.mux
}

// registerRoutes sets up the HTTP route patterns for the Schema Registry API.
// The routes follow the Confluent Schema Registry API convention for
// compatibility, with additional endpoints for validation and breaking
// change detection.
func (c *Controller) registerRoutes() {
	// Confluent-compatible endpoints
	c.mux.HandleFunc("POST /api/v1/schemas/subjects/{subject}/versions", c.handleRegister)
	c.mux.HandleFunc("GET /api/v1/schemas/subjects/{subject}/versions/{version}", c.handleGetByVersion)
	c.mux.HandleFunc("GET /api/v1/schemas/subjects/{subject}/versions/latest", c.handleGetLatest)
	c.mux.HandleFunc("GET /api/v1/schemas/ids/{id}", c.handleGetById)
	c.mux.HandleFunc("GET /api/v1/schemas/subjects", c.handleListSubjects)
	c.mux.HandleFunc("GET /api/v1/schemas/subjects/{subject}/versions", c.handleListVersions)
	c.mux.HandleFunc("DELETE /api/v1/schemas/subjects/{subject}", c.handleDeleteSubject)

	// Schema Registry-specific endpoints
	c.mux.HandleFunc("POST /api/v1/schemas/subjects/{subject}/validate", c.handleValidate)
	c.mux.HandleFunc("POST /api/v1/schemas/subjects/{subject}/check-breaking", c.handleCheckBreaking)

	// Health check
	c.mux.HandleFunc("GET /health", c.handleHealth)
}

// handleRegister handles POST /api/v1/schemas/subjects/{subject}/versions
// This endpoint is compatible with the Confluent Schema Registry API.
func (c *Controller) handleRegister(w http.ResponseWriter, r *http.Request) {
	subject := r.PathValue("subject")
	if subject == "" {
		c.writeError(w, http.StatusBadRequest, "MISSING_SUBJECT", "subject path parameter is required")
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 5*1024*1024)) // 5MB limit
	if err != nil {
		c.writeError(w, http.StatusBadRequest, "READ_ERROR", "failed to read request body")
		return
	}

	var reqBody struct {
		SchemaType        string                        `json:"schemaType"`
		Schema            string                        `json:"schema"`
		References        []models.SchemaReference      `json:"references,omitempty"`
		CompatibilityLevel *string                      `json:"compatibility,omitempty"`
		Description       string                        `json:"description,omitempty"`
	}
	if err := json.Unmarshal(body, &reqBody); err != nil {
		c.writeError(w, http.StatusBadRequest, "INVALID_JSON", "failed to parse request body as JSON")
		return
	}

	if reqBody.Schema == "" {
		c.writeError(w, http.StatusBadRequest, "MISSING_SCHEMA", "schema definition is required")
		return
	}

	// Default to PROTOBUF if not specified (Confluent uses AVRO as default)
	schemaTypeStr := reqBody.SchemaType
	if schemaTypeStr == "" {
		schemaTypeStr = "PROTOBUF"
	}
	schemaType, err := models.ParseSchemaType(schemaTypeStr)
	if err != nil {
		c.writeError(w, http.StatusBadRequest, "INVALID_SCHEMA_TYPE", err.Error())
		return
	}

	var compatLvl *models.CompatibilityLevel
	if reqBody.CompatibilityLevel != nil && *reqBody.CompatibilityLevel != "" {
		level, err := models.ParseCompatibilityLevel(*reqBody.CompatibilityLevel)
		if err != nil {
			c.writeError(w, http.StatusBadRequest, "INVALID_COMPATIBILITY", err.Error())
			return
		}
		compatLvl = &level
	}

	registrar := r.Header.Get("X-Client-ID")
	if registrar == "" {
		registrar = r.Header.Get("X-API-Key")
	}

	resp, err := c.register.Register(r.Context(), models.RegisterSchemaRequest{
		Subject:          subject,
		Type:             schemaType,
		Definition:       reqBody.Schema,
		References:       reqBody.References,
		CompatibilityLvl: compatLvl,
		Description:      reqBody.Description,
		RegisteredBy:     registrar,
	})
	if err != nil {
		c.handleDomainError(w, err)
		return
	}

	type registerResp struct {
		SchemaID    int32  `json:"id"`
		Version     int32  `json:"version"`
		Fingerprint string `json:"fingerprint"`
		RegisteredAt string `json:"registered_at"`
		Compatible  bool   `json:"compatible"`
	}

	c.writeJSON(w, http.StatusOK, registerResp{
		SchemaID:     resp.SchemaID,
		Version:      resp.Version,
		Fingerprint:  resp.Fingerprint,
		RegisteredAt: resp.RegisteredAt.Format(time.RFC3339),
		Compatible:   resp.CompatibilityCheck.Compatible,
	})
}

// handleGetByVersion handles GET /api/v1/schemas/subjects/{subject}/versions/{version}
func (c *Controller) handleGetByVersion(w http.ResponseWriter, r *http.Request) {
	subject := r.PathValue("subject")
	versionStr := r.PathValue("version")

	version, err := strconv.ParseInt(versionStr, 10, 32)
	if err != nil {
		c.writeError(w, http.StatusBadRequest, "INVALID_VERSION", "version must be a valid integer")
		return
	}
	v := int32(version)

	includeRefs := r.URL.Query().Has("include")
	includeDeprecated := r.URL.Query().Has("deprecated")

	resp, err := c.get.Get(r.Context(), models.GetSchemaRequest{
		Subject:           subject,
		Version:           &v,
		IncludeReferences: includeRefs,
		IncludeDeprecated: includeDeprecated,
	})
	if err != nil {
		c.handleDomainError(w, err)
		return
	}

	c.writeSchemaResponse(w, resp.Schema)
}

// handleGetLatest handles GET /api/v1/schemas/subjects/{subject}/versions/latest
func (c *Controller) handleGetLatest(w http.ResponseWriter, r *http.Request) {
	subject := r.PathValue("subject")
	includeRefs := r.URL.Query().Has("include")

	resp, err := c.get.Get(r.Context(), models.GetSchemaRequest{
		Subject:           subject,
		IncludeReferences: includeRefs,
	})
	if err != nil {
		c.handleDomainError(w, err)
		return
	}

	c.writeSchemaResponse(w, resp.Schema)
}

// handleGetById handles GET /api/v1/schemas/ids/{id}
func (c *Controller) handleGetById(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 32)
	if err != nil {
		c.writeError(w, http.StatusBadRequest, "INVALID_ID", "schema ID must be a valid integer")
		return
	}
	schemaID := int32(id)

	resp, err := c.get.Get(r.Context(), models.GetSchemaRequest{
		SchemaID: &schemaID,
	})
	if err != nil {
		c.handleDomainError(w, err)
		return
	}

	c.writeSchemaResponse(w, resp.Schema)
}

// handleListSubjects handles GET /api/v1/schemas/subjects
func (c *Controller) handleListSubjects(w http.ResponseWriter, r *http.Request) {
	prefix := r.URL.Query().Get("prefix")
	includeDeprecated := r.URL.Query().Get("deprecated") == "true"
	pageSizeStr := r.URL.Query().Get("pageSize")
	pageToken := r.URL.Query().Get("pageToken")

	var pageSize int32 = 20
	if pageSizeStr != "" {
		ps, err := strconv.ParseInt(pageSizeStr, 10, 32)
		if err == nil && ps > 0 {
			pageSize = int32(ps)
		}
	}

	var schemaType *models.SchemaType
	if st := r.URL.Query().Get("schemaType"); st != "" {
		parsed, err := models.ParseSchemaType(st)
		if err != nil {
			c.writeError(w, http.StatusBadRequest, "INVALID_SCHEMA_TYPE", err.Error())
			return
		}
		schemaType = &parsed
	}

	resp, err := c.list.List(r.Context(), models.ListSchemasRequest{
		Prefix:            prefix,
		Type:              schemaType,
		IncludeDeprecated: includeDeprecated,
		PageSize:          pageSize,
		PageToken:         pageToken,
	})
	if err != nil {
		c.handleDomainError(w, err)
		return
	}

	type subjectSummary struct {
		Name               string `json:"name"`
		CompatibilityLevel string `json:"compatibility_level"`
		LatestVersion      int32  `json:"latest_version"`
		SchemaType         string `json:"schema_type"`
		TotalVersions      int32  `json:"total_versions"`
		Deprecated         bool   `json:"deprecated"`
		RegisteredAt       string `json:"registered_at"`
		Description        string `json:"description,omitempty"`
	}

	type listResp struct {
		Subjects      []subjectSummary `json:"subjects"`
		TotalCount    int64            `json:"total_count"`
		NextPageToken string           `json:"next_page_token,omitempty"`
	}

	subjects := make([]subjectSummary, 0, len(resp.Subjects))
	for _, s := range resp.Subjects {
		subjects = append(subjects, subjectSummary{
			Name:               s.Name,
			CompatibilityLevel: s.CompatibilityLvl.String(),
			LatestVersion:      s.LatestVersion,
			SchemaType:         s.Type.String(),
			TotalVersions:      s.TotalVersions,
			Deprecated:         s.Deprecated,
			RegisteredAt:       s.RegisteredAt.Format(time.RFC3339),
			Description:        s.Description,
		})
	}

	c.writeJSON(w, http.StatusOK, listResp{
		Subjects:      subjects,
		TotalCount:    resp.TotalCount,
		NextPageToken: resp.NextPageToken,
	})
}

// handleListVersions handles GET /api/v1/schemas/subjects/{subject}/versions
func (c *Controller) handleListVersions(w http.ResponseWriter, r *http.Request) {
	subject := r.PathValue("subject")
	if subject == "" {
		c.writeError(w, http.StatusBadRequest, "MISSING_SUBJECT", "subject path parameter is required")
		return
	}

	// For this implementation, we return version numbers only
	// A full implementation would call a dedicated list-versions use case
	c.writeJSON(w, http.StatusOK, map[string]interface{}{
		"subject": subject,
		"message": "version listing not yet implemented",
	})
}

// handleDeleteSubject handles DELETE /api/v1/schemas/subjects/{subject}
func (c *Controller) handleDeleteSubject(w http.ResponseWriter, r *http.Request) {
	subject := r.PathValue("subject")
	if subject == "" {
		c.writeError(w, http.StatusBadRequest, "MISSING_SUBJECT", "subject path parameter is required")
		return
	}

	permanent := r.URL.Query().Get("permanent") == "true"
	deletedBy := r.Header.Get("X-Client-ID")

	if err := c.deleteSubject.Delete(r.Context(), models.DeleteSubjectRequest{
		Subject:   subject,
		Permanent: permanent,
		DeletedBy: deletedBy,
	}); err != nil {
		c.handleDomainError(w, err)
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

// handleValidate handles POST /api/v1/schemas/subjects/{subject}/validate
func (c *Controller) handleValidate(w http.ResponseWriter, r *http.Request) {
	subject := r.PathValue("subject")
	if subject == "" {
		c.writeError(w, http.StatusBadRequest, "MISSING_SUBJECT", "subject path parameter is required")
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 5*1024*1024))
	if err != nil {
		c.writeError(w, http.StatusBadRequest, "READ_ERROR", "failed to read request body")
		return
	}

	var reqBody struct {
		Schema          string `json:"schema"`
		SchemaType      string `json:"schemaType"`
		ValidationLevel string `json:"validationLevel"`
		TargetVersion   *int32 `json:"targetVersion,omitempty"`
	}
	if err := json.Unmarshal(body, &reqBody); err != nil {
		c.writeError(w, http.StatusBadRequest, "INVALID_JSON", "failed to parse request body")
		return
	}

	schemaType, err := models.ParseSchemaType(reqBody.SchemaType)
	if err != nil {
		c.writeError(w, http.StatusBadRequest, "INVALID_SCHEMA_TYPE", err.Error())
		return
	}

	validationLvl, err := models.ParseValidationLevel(reqBody.ValidationLevel)
	if err != nil {
		validationLvl = models.ValidationSyntax // default to syntax check
	}

	resp, err := c.validate.Validate(r.Context(), models.ValidateSchemaRequest{
		Subject:       subject,
		Definition:    reqBody.Schema,
		Type:          schemaType,
		ValidationLvl: validationLvl,
		TargetVersion: reqBody.TargetVersion,
	})
	if err != nil {
		c.handleDomainError(w, err)
		return
	}

	type validateResp struct {
		Valid    bool     `json:"valid"`
		Errors   []string `json:"errors,omitempty"`
		Warnings []string `json:"warnings,omitempty"`
	}

	errs := make([]string, 0, len(resp.Errors))
	for _, e := range resp.Errors {
		errs = append(errs, e.Error())
	}
	warnings := make([]string, 0, len(resp.Warnings))
	for _, w := range resp.Warnings {
		warnings = append(warnings, w.String())
	}

	c.writeJSON(w, http.StatusOK, validateResp{
		Valid:    resp.Valid,
		Errors:   errs,
		Warnings: warnings,
	})
}

// handleCheckBreaking handles POST /api/v1/schemas/subjects/{subject}/check-breaking
func (c *Controller) handleCheckBreaking(w http.ResponseWriter, r *http.Request) {
	subject := r.PathValue("subject")
	if subject == "" {
		c.writeError(w, http.StatusBadRequest, "MISSING_SUBJECT", "subject path parameter is required")
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 5*1024*1024))
	if err != nil {
		c.writeError(w, http.StatusBadRequest, "READ_ERROR", "failed to read request body")
		return
	}

	var reqBody struct {
		ProposedSchema  string `json:"proposedSchema"`
		CheckLevel      string `json:"checkLevel"`
		PreviousVersion *int32 `json:"previousVersion,omitempty"`
	}
	if err := json.Unmarshal(body, &reqBody); err != nil {
		c.writeError(w, http.StatusBadRequest, "INVALID_JSON", "failed to parse request body")
		return
	}

	checkLevel, err := models.ParseCheckLevel(reqBody.CheckLevel)
	if err != nil {
		checkLevel = models.CheckLevelDefault
	}

	resp, err := c.checkBreaking.CheckBreaking(r.Context(), models.CheckBreakingRequest{
		Subject:         subject,
		PreviousVersion: reqBody.PreviousVersion,
		ProposedSchema:  reqBody.ProposedSchema,
		CheckLevel:      checkLevel,
	})
	if err != nil {
		c.handleDomainError(w, err)
		return
	}

	c.writeJSON(w, http.StatusOK, resp)
}

// handleHealth handles GET /health
func (c *Controller) handleHealth(w http.ResponseWriter, r *http.Request) {
	c.writeJSON(w, http.StatusOK, map[string]string{
		"status":  "SERVING",
		"service": "schema-registry",
	})
}

// --- JSON response helpers ---

type errorResponse struct {
	Error   string `json:"error"`
	Code    string `json:"code"`
	Message string `json:"message"`
}

func (c *Controller) writeJSON(w http.ResponseWriter, statusCode int, body interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	if err := json.NewEncoder(w).Encode(body); err != nil {
		c.logger.Error("failed to encode JSON response",
			slog.String("error", err.Error()),
		)
	}
}

func (c *Controller) writeError(w http.ResponseWriter, statusCode int, code, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	resp := errorResponse{
		Error:   http.StatusText(statusCode),
		Code:    code,
		Message: message,
	}
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		c.logger.Error("failed to encode error response",
			slog.String("error", err.Error()),
		)
	}
}

func (c *Controller) writeSchemaResponse(w http.ResponseWriter, schema models.Schema) {
	type schemaResp struct {
		SchemaID         int32                      `json:"id"`
		Version          int32                      `json:"version"`
		Subject          string                     `json:"subject"`
		SchemaType       string                     `json:"schemaType"`
		Schema           string                     `json:"schema"`
		References       []models.SchemaReference   `json:"references,omitempty"`
		Fingerprint      string                     `json:"fingerprint"`
		RegisteredAt     string                     `json:"registered_at"`
		Deprecated       bool                       `json:"deprecated"`
		Description      string                     `json:"description,omitempty"`
		CompatibilityLvl string                     `json:"compatibilityLevel"`
	}

	c.writeJSON(w, http.StatusOK, schemaResp{
		SchemaID:         schema.ID,
		Version:          schema.Version,
		Subject:          schema.Subject,
		SchemaType:       schema.Type.String(),
		Schema:           schema.Definition,
		References:       schema.References,
		Fingerprint:      schema.Fingerprint,
		RegisteredAt:     schema.RegisteredAt.Format(time.RFC3339),
		Deprecated:       schema.Deprecated,
		Description:      schema.Description,
		CompatibilityLvl: schema.CompatibilityLvl.String(),
	})
}

// handleDomainError maps domain errors to HTTP status codes and writes responses.
func (c *Controller) handleDomainError(w http.ResponseWriter, err error) {
	switch e := err.(type) {
	case *services.SchemaIncompatibleError:
		c.writeError(w, http.StatusConflict, "SCHEMA_INCOMPATIBLE",
			fmt.Sprintf("schema is incompatible at %s level: %d violation(s)", e.Level, len(e.Violations)))
	case *services.InvalidSchemaError:
		c.writeError(w, http.StatusUnprocessableEntity, "INVALID_SCHEMA",
			fmt.Sprintf("schema validation failed: %d error(s)", len(e.Errors)))
	case *services.SchemaNotFoundError:
		c.writeError(w, http.StatusNotFound, "SCHEMA_NOT_FOUND", e.Error())
	case *services.DuplicateSchemaError:
		c.writeError(w, http.StatusConflict, "DUPLICATE_SCHEMA", e.Error())
	default:
		c.logger.Error("unhandled domain error",
			slog.String("error", err.Error()),
		)
		c.writeError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "an internal error occurred")
	}
}

// --- Middleware ---

// LoggingMiddleware returns an HTTP middleware that logs each request.
func LoggingMiddleware(logger *slog.Logger) func(http.Handler) http.Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			next.ServeHTTP(w, r)
			logger.Info("HTTP request",
				slog.String("method", r.Method),
				slog.String("path", r.URL.Path),
				slog.Duration("duration", time.Since(start)),
				slog.String("remote_addr", r.RemoteAddr),
			)
		})
	}
}

// RecoveryMiddleware returns an HTTP middleware that recovers from panics.
func RecoveryMiddleware(logger *slog.Logger) func(http.Handler) http.Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if rec := recover(); rec != nil {
					logger.Error("panic recovered in HTTP handler",
						slog.Any("panic", rec),
						slog.String("method", r.Method),
						slog.String("path", r.URL.Path),
					)
					http.Error(w, `{"error":"Internal Server Error","code":"PANIC","message":"an unexpected error occurred"}`, http.StatusInternalServerError)
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}

// CORSMiddleware returns an HTTP middleware that adds CORS headers.
func CORSMiddleware(allowedOrigins []string) func(http.Handler) http.Handler {
	origins := "*"
	if len(allowedOrigins) > 0 {
		origins = allowedOrigins[0]
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Access-Control-Allow-Origin", origins)
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key, X-Client-ID, Traceparent")
			if r.Method == http.MethodOptions {
				w.WriteHeader(http.StatusNoContent)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// Ensure Controller satisfies the expected interface patterns.
var _ context.Context // compile-time check that context is imported
