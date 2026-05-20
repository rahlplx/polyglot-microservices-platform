// Package models defines the ValidationResult and ValidationError types
// used by the Schema Registry validation pipeline. Validation is a multi-stage
// process that checks schemas for syntax correctness, semantic conventions,
// compatibility with previous versions, and full Buf lint compliance.
package models

// ValidationLevel defines the depth of validation to perform. Each level
// builds upon the previous one, providing progressively more thorough
// analysis of the schema definition.
type ValidationLevel int

const (
	// ValidationSyntax checks that the schema is well-formed and parseable.
	// For Protobuf, this verifies that the proto file can be parsed by the
	// protoc compiler. For Avro, it validates the JSON schema structure.
	// For JSON Schema, it checks that the schema itself is valid JSON.
	ValidationSyntax ValidationLevel = iota

	// ValidationSemantic adds naming convention checks and style guidelines
	// on top of syntax validation. For Protobuf, this includes snake_case
	// field naming, required comments on messages and fields, and package
	// naming conventions.
	ValidationSemantic

	// ValidationCompatibility checks the schema against the latest registered
	// version for the subject, using the configured compatibility level. This
	// ensures that the proposed schema does not introduce breaking changes.
	ValidationCompatibility

	// ValidationFull performs all validation levels including Buf lint rules
	// and breaking change detection. This is the most comprehensive level
	// and should be used in CI/CD pipelines before merging schema changes.
	ValidationFull
)

// String returns a human-readable representation of the ValidationLevel.
func (v ValidationLevel) String() string {
	names := [...]string{"SYNTAX", "SEMANTIC", "COMPATIBILITY", "FULL"}
	if v < 0 || int(v) >= len(names) {
		return "UNKNOWN"
	}
	return names[v]
}

// ParseValidationLevel converts a string to a ValidationLevel.
func ParseValidationLevel(s string) (ValidationLevel, error) {
	switch s {
	case "SYNTAX":
		return ValidationSyntax, nil
	case "SEMANTIC":
		return ValidationSemantic, nil
	case "COMPATIBILITY":
		return ValidationCompatibility, nil
	case "FULL":
		return ValidationFull, nil
	default:
		return ValidationSyntax, errUnknownValidationLevel(s)
	}
}

// errUnknownValidationLevel creates an error for an unrecognized validation level string.
func errUnknownValidationLevel(s string) error {
	return &ValidationError{
		Message:  "unknown validation level: " + s,
		Location: "",
		RuleID:   "INVALID_VALIDATION_LEVEL",
	}
}

// ValidationError represents an error found during schema validation.
// Errors are issues that must be fixed before the schema can be registered.
// Each error includes a human-readable message, the location within the
// schema definition where the error was found, and the rule identifier
// that triggered the error.
type ValidationError struct {
	Message  string // Human-readable error description
	Location string // Location in the schema (e.g., "line 15, column 3")
	RuleID   string // Identifier of the violated rule (e.g., "FIELD_LOWER_SNAKE_CASE")
}

// Error implements the error interface for ValidationError.
func (e *ValidationError) Error() string {
	if e.Location != "" {
		return e.Location + ": " + e.Message + " [" + e.RuleID + "]"
	}
	return e.Message + " [" + e.RuleID + "]"
}

// ValidationWarning represents a warning found during schema validation.
// Warnings are issues that should be reviewed but do not block schema
// registration. They typically indicate style violations or potential
// issues that are not strictly breaking.
type ValidationWarning struct {
	Message  string // Human-readable warning description
	Location string // Location in the schema (e.g., "line 42, column 1")
	RuleID   string // Identifier of the violated rule (e.g., "PACKAGE_IS_LOWER_SNAKE_CASE")
}

// String returns a formatted representation of the validation warning.
func (w ValidationWarning) String() string {
	if w.Location != "" {
		return w.Location + ": " + w.Message + " [" + w.RuleID + "]"
	}
	return w.Message + " [" + w.RuleID + "]"
}

// ValidateSchemaRequest is the domain-level input for the schema validation
// use case. It specifies the schema to validate, the validation depth, and
// optionally a target version for compatibility checking.
type ValidateSchemaRequest struct {
	Subject       string          // Subject to validate against
	Definition    string          // Raw schema definition to validate
	Type          SchemaType      // Schema type
	ValidationLvl ValidationLevel // Depth of validation to perform
	TargetVersion *int32          // Reference version for compatibility check (nil = latest)
}

// ValidateSchemaResponse is the domain-level output of the schema validation
// use case. It includes the overall validity, any errors and warnings found,
// and optionally the result of the compatibility check.
type ValidateSchemaResponse struct {
	Valid               bool                 // Whether the schema passed all validation checks
	Errors              []ValidationError    // Errors that must be fixed before registration
	Warnings            []ValidationWarning  // Warnings that should be reviewed
	CompatibilityResult *CompatibilityResult // Result of compatibility check (nil if not checked)
}
