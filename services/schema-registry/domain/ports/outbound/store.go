// Package outbound defines the driven port interfaces (infrastructure interfaces)
// for the Schema Registry domain. These interfaces represent the capabilities that
// the Schema Registry needs from infrastructure components such as databases,
// compilers, and external validation tools.
// ZERO external dependencies — only stdlib and domain types.
package outbound

import (
	"context"

	"github.com/gstack/schema-registry-service/domain/models"
)

// SchemaRepository defines the interface for persisting and retrieving schema
// records. The repository manages all database interactions including schema
// storage, version tracking, fingerprint-based deduplication, and subject
// lifecycle management (soft-delete and permanent deletion).
type SchemaRepository interface {
	// Save persists a schema record with version and metadata. The repository
	// assigns a unique schema ID and ensures the (subject, version) pair is
	// unique using a database constraint. Returns the saved record with the
	// assigned ID.
	Save(ctx context.Context, schema models.Schema) (models.Schema, error)

	// FindBySubject retrieves all versions of a schema by subject name,
	// ordered by version number (ascending). Returns an empty slice if
	// no versions exist for the subject.
	FindBySubject(ctx context.Context, subject string) ([]models.Schema, error)

	// FindBySubjectAndVersion retrieves a specific schema version. Returns
	// nil if the subject or version does not exist.
	FindBySubjectAndVersion(ctx context.Context, subject string, version int32) (*models.Schema, error)

	// FindLatestBySubject retrieves the latest (highest version) schema for
	// a subject. Returns nil if the subject does not exist.
	FindLatestBySubject(ctx context.Context, subject string) (*models.Schema, error)

	// FindById retrieves a schema by its global unique ID. Returns nil
	// if no schema with the given ID exists.
	FindById(ctx context.Context, schemaID int32) (*models.Schema, error)

	// FindByFingerprint looks up a schema by its content fingerprint.
	// This is used for fast deduplication checks during registration.
	// Returns nil if no schema with the given fingerprint exists.
	FindByFingerprint(ctx context.Context, subject, fingerprint string) (*models.Schema, error)

	// DeleteSubject removes a subject and all its versions. If permanent
	// is true, the data is physically removed; otherwise it is soft-deleted.
	DeleteSubject(ctx context.Context, subject string, permanent bool) error

	// ListSubjects returns a list of subject names matching the optional
	// prefix filter. If prefix is empty, all subjects are returned.
	ListSubjects(ctx context.Context, prefix string) ([]string, error)

	// CountSubjects returns the total number of registered subjects matching
	// the optional prefix filter. This is used for pagination metadata.
	CountSubjects(ctx context.Context, prefix string) (int64, error)

	// GetNextVersion returns the next version number for a subject. If the
	// subject does not exist, it returns 1. Otherwise, it returns the
	// highest existing version number plus one.
	GetNextVersion(ctx context.Context, subject string) (int32, error)
}

// ProtoCompiler defines the interface for compiling Protobuf schema definitions.
// The compiler validates syntax, resolves type references, and produces
// compilation results including any errors or warnings. This port abstracts
// the specific compiler implementation (e.g., buf build or direct protoc).
type ProtoCompiler interface {
	// Compile validates a Protobuf schema definition by compiling it with its
	// dependencies. Returns a CompilationResult with any errors found. The
	// includes parameter provides additional proto files that the schema
	// references via import statements.
	Compile(ctx context.Context, schemaDef string, includes []models.SchemaReference) (CompilationResult, error)
}

// CompilationResult holds the outcome of a proto compilation attempt. It
// includes any errors that prevented successful compilation and warnings
// that indicate non-fatal issues.
type CompilationResult struct {
	Success bool              // Whether the compilation succeeded
	Errors  []models.ValidationError  // Compilation errors
	Warnings []models.ValidationWarning // Compilation warnings
}

// SchemaValidator defines the interface for validating schema definitions
// against style guidelines, naming conventions, and breaking change rules.
// This port abstracts the validation engine (e.g., Buf lint and breaking
// change detection) from the domain logic.
type SchemaValidator interface {
	// Lint runs style and naming convention checks on a schema definition.
	// Returns a list of errors and warnings found during linting. The
	// lint rules enforce best practices such as snake_case field names
	// and required comments on messages and fields.
	Lint(ctx context.Context, schemaDef string) ([]models.ValidationError, []models.ValidationWarning, error)

	// CheckBreaking performs breaking change detection between a proposed
	// schema and a previous version. The check level controls the strictness
	// of the analysis. Returns a list of detected breaking changes with
	// severity levels and mitigation suggestions.
	CheckBreaking(ctx context.Context, previousDef, proposedDef string, level models.CheckLevel) (models.CheckBreakingResponse, error)
}

// EventPublisher defines the interface for publishing domain events when
// schema changes occur. Events are published to Kafka topics for downstream
// consumers such as the CDC Relay and Analytics services.
type EventPublisher interface {
	// PublishSchemaRegistered publishes a schema-registered event after a
	// successful schema registration. The event includes the subject, version,
	// schema ID, fingerprint, and the result of the compatibility check.
	PublishSchemaRegistered(ctx context.Context, schema models.Schema, compatResult models.CompatibilityResult) error

	// PublishCompatibilityViolation publishes a compatibility-violation event
	// when an automated compatibility check detects a potential incompatibility.
	// This serves as an early warning system for service owners.
	PublishCompatibilityViolation(ctx context.Context, subject string, violations []models.CompatibilityViolation) error
}
