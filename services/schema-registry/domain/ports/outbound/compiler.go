// Package outbound defines the ProtoCompiler port for the Schema Registry.
// This file provides the compiler interface and related types.
package outbound

import (
	"context"

	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/models"
)

// ProtoCompilerPort defines the interface for compiling and validating
// Protobuf schema definitions. The port abstracts the specific compiler
// implementation (Buf CLI or direct protoc) from the domain logic.
// The compiler is responsible for syntax validation, type reference
// resolution, and FileDescriptorSet extraction.
type ProtoCompilerPort interface {
	// Compile validates a Protobuf schema definition by compiling it.
	// Returns a CompilationResult with any errors or warnings found.
	// The includes parameter provides the definitions of imported proto files.
	Compile(ctx context.Context, schemaDef string, includes []models.Schema) (CompilationResult, error)

	// ResolveReferences resolves all import references transitively for
	// a given schema definition. Returns the list of proto files that
	// the schema depends on, in dependency order.
	ResolveReferences(ctx context.Context, schemaDef string, available []models.Schema) ([]models.Schema, error)
}
