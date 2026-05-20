// Package models defines the core domain models for the Schema Registry service.
// These types have ZERO external dependencies — only stdlib and domain types.
// The Schema entity is the central domain object, representing a versioned
// schema definition registered under a unique subject name.
package models

import (
	"crypto/sha256"
	"fmt"
	"time"
)

// SchemaType represents the type of schema definition. The registry supports
// three schema formats: Protobuf (the primary format for gRPC services),
// Avro (commonly used with Kafka and event streaming), and JSON Schema
// (used for REST API request/response validation).
type SchemaType int

const (
	SchemaTypeProtobuf   SchemaType = iota // Protobuf schema (primary)
	SchemaTypeAvro                         // Apache Avro schema
	SchemaTypeJSONSchema                   // JSON Schema definition
)

// String returns a human-readable representation of the SchemaType.
// This is used in API responses, logging, and metric labels.
func (s SchemaType) String() string {
	names := [...]string{"PROTOBUF", "AVRO", "JSON_SCHEMA"}
	if s < 0 || int(s) >= len(names) {
		return "UNKNOWN"
	}
	return names[s]
}

// ParseSchemaType converts a string representation to a SchemaType.
// Returns an error if the string does not match any known schema type.
// This is used when parsing incoming API requests.
func ParseSchemaType(s string) (SchemaType, error) {
	switch s {
	case "PROTOBUF":
		return SchemaTypeProtobuf, nil
	case "AVRO":
		return SchemaTypeAvro, nil
	case "JSON_SCHEMA":
		return SchemaTypeJSONSchema, nil
	default:
		return SchemaTypeProtobuf, fmt.Errorf("unknown schema type: %q", s)
	}
}

// SchemaReference represents a reference from one schema to another. Protobuf
// schemas commonly reference other proto files via import statements. The
// registry tracks these references to support transitive resolution and
// dependency-aware compatibility checking.
type SchemaReference struct {
	Name    string // Reference name (e.g., the import path for proto files)
	Subject string // Subject of the referenced schema
	Version int32  // Version of the referenced schema
}

// Schema is the central domain entity representing a versioned schema definition.
// Each schema belongs to a subject (a logical grouping, typically a file path
// like "identity/v1/identity.proto") and has a monotonically increasing version
// number. The fingerprint provides a content-based deduplication mechanism:
// two identical schema definitions will produce the same fingerprint, allowing
// the registry to detect and reject duplicate registrations efficiently.
type Schema struct {
	ID               int32              // Unique schema identifier (auto-incremented)
	Subject          string             // Subject name (e.g., "order/v1/order.proto")
	Version          int32              // Version number within the subject (monotonically increasing)
	Type             SchemaType         // Schema type (PROTOBUF, AVRO, JSON_SCHEMA)
	Definition       string             // Raw schema definition content
	References       []SchemaReference  // Schema dependencies (transitive imports)
	Fingerprint      string             // SHA-256 fingerprint of the canonical schema definition
	CompatibilityLvl CompatibilityLevel // Compatibility level for this subject
	Deprecated       bool               // Whether this version is deprecated
	Description      string             // Optional human-readable description
	RegisteredAt     time.Time          // Timestamp when this schema was registered
	RegisteredBy     string             // Identity of the registrar (SPIFFE ID or service account)
}

// ComputeFingerprint calculates the SHA-256 fingerprint of the schema definition.
// The fingerprint is used for content-based deduplication: if two schema definitions
// have the same canonical form, they will produce the same fingerprint, and the
// registry can return the existing schema ID instead of creating a duplicate.
func (s *Schema) ComputeFingerprint() string {
	hash := sha256.Sum256([]byte(s.Definition))
	return fmt.Sprintf("%x", hash)
}

// SubjectInfo holds metadata about a schema subject, including its compatibility
// level and the count of registered versions. This is used in subject listing
// and summary responses.
type SubjectInfo struct {
	Name             string             // Subject name
	CompatibilityLvl CompatibilityLevel // Configured compatibility level
	LatestVersion    int32              // Highest version number
	Type             SchemaType         // Schema type of the latest version
	TotalVersions    int32              // Total number of registered versions
	Deprecated       bool               // Whether the latest version is deprecated
	RegisteredAt     time.Time          // Registration timestamp of the latest version
	Description      string             // Description of the latest version
}

// RegisterSchemaRequest is the domain-level input for the schema registration
// use case. It contains the schema definition, type, references, and optional
// configuration overrides.
type RegisterSchemaRequest struct {
	Subject          string              // Subject to register under
	Type             SchemaType          // Schema type
	Definition       string              // Raw schema definition
	References       []SchemaReference   // Schema dependencies
	CompatibilityLvl *CompatibilityLevel // Optional override for compatibility level
	Description      string              // Optional description
	RegisteredBy     string              // Identity of the registrar
}

// RegisterSchemaResponse is the domain-level output of the schema registration
// use case. It includes the assigned schema ID and version, along with the
// result of the compatibility check performed during registration.
type RegisterSchemaResponse struct {
	SchemaID           int32               // Assigned schema ID
	Version            int32               // Assigned version number
	Fingerprint        string              // Computed content fingerprint
	RegisteredAt       time.Time           // Registration timestamp
	CompatibilityCheck CompatibilityResult // Result of the compatibility check
}

// GetSchemaRequest is the domain-level input for the schema retrieval use case.
// It supports lookup by subject+version or by global schema ID.
type GetSchemaRequest struct {
	Subject           string // Subject name (required for subject-based lookup)
	Version           *int32 // Version number (nil = latest version)
	SchemaID          *int32 // Global schema ID (alternative to subject+version)
	IncludeReferences bool   // Whether to resolve and include transitive references
	IncludeDeprecated bool   // Whether to include deprecated versions in search
}

// GetSchemaResponse is the domain-level output of the schema retrieval use case.
// It includes the full schema definition and metadata.
type GetSchemaResponse struct {
	Schema Schema // The retrieved schema entity
}

// ListSchemasRequest is the domain-level input for the schema listing use case.
// It supports filtering and cursor-based pagination.
type ListSchemasRequest struct {
	Prefix            string      // Subject prefix filter (e.g., "order/v1/")
	Type              *SchemaType // Schema type filter (nil = all types)
	IncludeDeprecated bool        // Whether to include deprecated subjects
	PageSize          int32       // Number of results per page (default: 20)
	PageToken         string      // Opaque cursor for pagination
}

// ListSchemasResponse is the domain-level output of the schema listing use case.
type ListSchemasResponse struct {
	Subjects      []SubjectInfo // Subject summaries
	TotalCount    int64         // Total number of matching subjects
	NextPageToken string        // Cursor for the next page (empty if no more results)
}

// DeleteSubjectRequest is the domain-level input for the subject deletion use case.
type DeleteSubjectRequest struct {
	Subject   string // Subject to delete
	Permanent bool   // If true, permanently remove data; otherwise soft-delete
	DeletedBy string // Identity of the requester
}
