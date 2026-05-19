// Package inbound defines the driving port interfaces (use cases) for the
// Schema Registry domain. These interfaces represent the capabilities that
// the Schema Registry exposes to the outside world through its API adapters.
// ZERO external dependencies — only stdlib and domain types.
package inbound

import (
	"context"

	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/models"
)

// RegisterSchemaUseCase defines the schema registration capability. Implementations
// accept a schema definition, validate it for syntax and compatibility, and persist
// it as a new version under the specified subject. This is the primary write
// operation in the Schema Registry and enforces all compatibility guarantees.
type RegisterSchemaUseCase interface {
	// Register validates and registers a new schema version under the given subject.
	// It first validates the schema definition for syntactic correctness, then checks
	// compatibility against the latest registered version using the configured
	// compatibility level. If the schema is incompatible, it returns a
	// SchemaIncompatibleError with detailed violation information. If the schema
	// definition is identical to an existing version (same fingerprint), it returns
	// the existing schema ID without creating a duplicate.
	Register(ctx context.Context, req models.RegisterSchemaRequest) (models.RegisterSchemaResponse, error)
}

// GetSchemaUseCase defines the schema retrieval capability. Implementations
// support lookup by subject+version, by global schema ID, and by fingerprint.
// The registry maintains a two-level cache for fast lookups.
type GetSchemaUseCase interface {
	// Get retrieves a schema by subject and version, or by global schema ID.
	// When version is nil, it returns the latest version for the subject.
	// When includeReferences is true, it recursively resolves all schema
	// dependencies and includes their definitions in the response.
	Get(ctx context.Context, req models.GetSchemaRequest) (models.GetSchemaResponse, error)
}

// ListSchemasUseCase defines the schema listing capability. Implementations
// support filtering by subject prefix, schema type, and deprecation status,
// with cursor-based pagination for efficient browsing of large registries.
type ListSchemasUseCase interface {
	// List returns a paginated list of schema subjects matching the given
	// filter criteria. Each entry includes a summary with the subject name,
	// latest version, schema type, total versions, and deprecation status.
	List(ctx context.Context, req models.ListSchemasRequest) (models.ListSchemasResponse, error)
}

// ValidateSchemaUseCase defines the schema validation capability. Implementations
// validate a schema definition without registering it, supporting multiple
// validation levels from basic syntax checking to full Buf lint analysis.
type ValidateSchemaUseCase interface {
	// Validate checks a schema definition without persisting it. The validation
	// level controls the depth of analysis: SYNTAX checks parseability, SEMANTIC
	// adds naming convention checks, COMPATIBILITY checks against the latest
	// version, and FULL adds Buf lint and breaking change detection.
	Validate(ctx context.Context, req models.ValidateSchemaRequest) (models.ValidateSchemaResponse, error)
}

// CheckBreakingUseCase defines the breaking change detection capability.
// Implementations perform a detailed analysis comparing a proposed schema
// against a reference version, identifying all breaking changes with
// severity levels and mitigation suggestions.
type CheckBreakingUseCase interface {
	// CheckBreaking performs a comprehensive breaking change analysis between
	// a proposed schema and a reference version. The check level controls the
	// strictness of the analysis. The response includes all detected breaking
	// changes, their severity, and actionable mitigation suggestions.
	CheckBreaking(ctx context.Context, req models.CheckBreakingRequest) (models.CheckBreakingResponse, error)
}

// DeleteSubjectUseCase defines the subject deletion capability. Implementations
// support both soft deletion (marking as deleted, reversible) and permanent
// deletion (irreversible, for compliance-driven data removal).
type DeleteSubjectUseCase interface {
	// Delete removes a subject and all its versions. If permanent is true,
	// the data is physically removed; otherwise it is soft-deleted and can
	// be recovered by an administrator. Permanent deletion requires admin
	// authorization.
	Delete(ctx context.Context, req models.DeleteSubjectRequest) error
}
