// Package outbound defines the SchemaValidator port for the Schema Registry.
// This file provides the validator interface for lint and breaking change checks.
package outbound

import (
	"context"

	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/models"
)

// SchemaValidatorPort defines the interface for validating schema definitions
// against style guidelines and breaking change rules. The port abstracts the
// validation engine (Buf lint and buf breaking) from the domain logic,
// allowing the domain service to request validation without knowing the
// specific tool or configuration being used.
type SchemaValidatorPort interface {
	// Lint runs style and naming convention checks on a schema definition.
	// It returns errors that must be fixed and warnings that should be
	// reviewed. The lint rules enforce best practices such as snake_case
	// field naming, required comments on messages and fields, and package
	// naming conventions. The specific rules applied depend on the Buf
	// configuration, which can be customized per subject.
	Lint(ctx context.Context, schemaDef string) ([]models.ValidationError, []models.ValidationWarning, error)

	// CheckBreaking performs breaking change detection between a previous
	// schema version and a proposed new version. The check level controls
	// which rules are applied: MINIMAL checks only wire compatibility,
	// DEFAULT adds source compatibility checks, and STRICT adds all
	// available rules including documentation requirements.
	CheckBreaking(ctx context.Context, previousDef, proposedDef string, level models.CheckLevel) (models.CheckBreakingResponse, error)
}
