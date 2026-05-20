// Package models defines the CompatibilityLevel enum and CompatibilityResult
// types used throughout the Schema Registry domain. Compatibility checking
// is a core feature that prevents breaking changes from being registered,
// ensuring that consumers can always read data produced by older versions.
package models

import (
	"fmt"
)

// CompatibilityLevel defines the strictness of compatibility enforcement
// when registering a new schema version. Each level specifies which
// compatibility guarantees must hold between the new and previous versions.
// The NONE level disables checking entirely, while FULL provides the
// strongest guarantees (both backward and forward compatible).
type CompatibilityLevel int

const (
	// CompatibilityNone disables compatibility checking. Any schema change
	// is allowed, including breaking changes. Use this only for development
	// or non-critical subjects where breaking changes are acceptable.
	CompatibilityNone CompatibilityLevel = iota

	// CompatibilityBackward requires that the new schema can read data
	// produced by the previous version. This means consumers using the
	// new schema can deserialize messages written by the old schema.
	// Example: adding a new optional field is backward compatible.
	CompatibilityBackward

	// CompatibilityForward requires that the old schema can read data
	// produced by the new version. This means consumers using the old
	// schema can deserialize messages written by the new schema.
	// Example: removing an optional field is forward compatible.
	CompatibilityForward

	// CompatibilityFull requires both backward and forward compatibility.
	// The new schema must be able to read old data, and the old schema
	// must be able to read new data. This is the strictest level and
	// provides the strongest guarantees for schema evolution.
	CompatibilityFull

	// CompatibilityBackwardTransitive extends backward compatibility to
	// require that the new schema can read data from ALL previous versions,
	// not just the immediate predecessor. This is important when consumers
	// may be running any historical version of the schema.
	CompatibilityBackwardTransitive

	// CompatibilityForwardTransitive extends forward compatibility to
	// require that ALL previous schema versions can read data produced
	// by the new version. This provides strong guarantees for producers
	// that may still be running older code.
	CompatibilityForwardTransitive

	// CompatibilityFullTransitive combines both backward-transitive and
	// forward-transitive compatibility. This is the most restrictive level,
	// ensuring that any version can read data from any other version.
	CompatibilityFullTransitive
)

// String returns a human-readable representation of the CompatibilityLevel.
// This is used in API responses, logging, and metric labels.
func (c CompatibilityLevel) String() string {
	names := [...]string{
		"NONE",
		"BACKWARD",
		"FORWARD",
		"FULL",
		"BACKWARD_TRANSITIVE",
		"FORWARD_TRANSITIVE",
		"FULL_TRANSITIVE",
	}
	if c < 0 || int(c) >= len(names) {
		return "UNKNOWN"
	}
	return names[c]
}

// ParseCompatibilityLevel converts a string representation to a CompatibilityLevel.
// Returns an error if the string does not match any known level.
func ParseCompatibilityLevel(s string) (CompatibilityLevel, error) {
	levels := map[string]CompatibilityLevel{
		"NONE":                CompatibilityNone,
		"BACKWARD":            CompatibilityBackward,
		"FORWARD":             CompatibilityForward,
		"FULL":                CompatibilityFull,
		"BACKWARD_TRANSITIVE": CompatibilityBackwardTransitive,
		"FORWARD_TRANSITIVE":  CompatibilityForwardTransitive,
		"FULL_TRANSITIVE":     CompatibilityFullTransitive,
	}
	level, ok := levels[s]
	if !ok {
		return CompatibilityNone, fmt.Errorf("unknown compatibility level: %q", s)
	}
	return level, nil
}

// IsBackward returns true if the compatibility level includes backward
// compatibility requirements (BACKWARD, FULL, and their transitive variants).
func (c CompatibilityLevel) IsBackward() bool {
	return c == CompatibilityBackward ||
		c == CompatibilityFull ||
		c == CompatibilityBackwardTransitive ||
		c == CompatibilityFullTransitive
}

// IsForward returns true if the compatibility level includes forward
// compatibility requirements (FORWARD, FULL, and their transitive variants).
func (c CompatibilityLevel) IsForward() bool {
	return c == CompatibilityForward ||
		c == CompatibilityFull ||
		c == CompatibilityForwardTransitive ||
		c == CompatibilityFullTransitive
}

// IsTransitive returns true if the compatibility level requires checking
// against all previous versions rather than just the immediate predecessor.
func (c CompatibilityLevel) IsTransitive() bool {
	return c == CompatibilityBackwardTransitive ||
		c == CompatibilityForwardTransitive ||
		c == CompatibilityFullTransitive
}

// CompatibilityViolation describes a single compatibility rule violation
// detected during compatibility checking. Each violation includes the
// specific rule that was broken, the field or message affected, and
// the types involved in the incompatibility.
type CompatibilityViolation struct {
	Description  string // Human-readable description of the violation
	FieldPath    string // Path to the affected field or message (e.g., "Order.items")
	Rule         string // The compatibility rule that was violated
	PreviousType string // Type in the previous schema version
	ProposedType string // Type in the proposed schema version
}

// CompatibilityResult summarizes the outcome of a compatibility check between
// a proposed schema and one or more reference versions. It includes the overall
// compatibility verdict, the level at which the check was performed, and a list
// of any violations found.
type CompatibilityResult struct {
	Compatible       bool                     // Whether the schema is compatible
	Violations       []CompatibilityViolation // List of violations (empty if compatible)
	CompatibilityLvl CompatibilityLevel       // Level at which the check was performed
}

// CheckLevel defines the strictness of a breaking change analysis. The level
// controls which rules are applied during the check, from wire compatibility
// only (MINIMAL) to a comprehensive analysis including lint rules (STRICT).
type CheckLevel int

const (
	// CheckLevelMinimal checks only wire compatibility — changes that would
	// break binary deserialization. This catches the most critical breaking
	// changes such as changing field numbers or removing required fields.
	CheckLevelMinimal CheckLevel = iota

	// CheckLevelDefault checks both wire and source compatibility. In addition
	// to wire-level breaks, it detects changes that would break generated code
	// compilation, such as renaming a field or changing a message name.
	CheckLevelDefault

	// CheckLevelStrict applies all available rules including documentation
	// requirements, naming conventions, and style guidelines. This is the
	// most comprehensive check and should be used in CI/CD pipelines.
	CheckLevelStrict
)

// String returns a human-readable representation of the CheckLevel.
func (c CheckLevel) String() string {
	names := [...]string{"MINIMAL", "DEFAULT", "STRICT"}
	if c < 0 || int(c) >= len(names) {
		return "UNKNOWN"
	}
	return names[c]
}

// ParseCheckLevel converts a string to a CheckLevel.
func ParseCheckLevel(s string) (CheckLevel, error) {
	switch s {
	case "MINIMAL":
		return CheckLevelMinimal, nil
	case "DEFAULT":
		return CheckLevelDefault, nil
	case "STRICT":
		return CheckLevelStrict, nil
	default:
		return CheckLevelDefault, fmt.Errorf("unknown check level: %q", s)
	}
}

// BreakingChange represents a single breaking change detected between two
// schema versions. Each change includes the type of breakage, the affected
// field or message, and the category (WIRE, SOURCE, or FILE level).
type BreakingChange struct {
	ChangeType  string // Type of breaking change (e.g., "FIELD_REMOVED", "TYPE_CHANGED")
	FieldPath   string // Path to the affected field or message
	Description string // Human-readable description of the breakage
	Category    string // Category: WIRE, SOURCE, or FILE
}

// MitigationSuggestion provides an actionable recommendation for resolving
// a breaking change without requiring a version bump. This helps developers
// understand how to modify their proposed schema to maintain compatibility.
type MitigationSuggestion struct {
	ChangeType string // The breaking change type this suggestion addresses
	Suggestion string // The mitigation strategy
	Example    string // Example of the corrected schema
}

// CheckBreakingRequest is the domain-level input for the breaking change
// analysis use case.
type CheckBreakingRequest struct {
	Subject         string     // Subject of the proposed schema
	PreviousVersion *int32     // Reference version (nil = latest)
	ProposedSchema  string     // Proposed schema definition
	CheckLevel      CheckLevel // Strictness level for the analysis
}

// CheckBreakingResponse is the domain-level output of the breaking change
// analysis use case. It includes a list of all detected breaking changes,
// the overall severity, and mitigation suggestions.
type CheckBreakingResponse struct {
	HasBreakingChanges bool                   // Whether any breaking changes were detected
	Changes            []BreakingChange       // List of detected breaking changes
	Severity           string                 // Overall severity: INFO, WARNING, or ERROR
	Mitigations        []MitigationSuggestion // Suggested fixes for each breaking change
}

// BreakingChangeRule defines a configurable rule for breaking change detection.
// Rules can be individually enabled or disabled per subject or per check request.
type BreakingChangeRule struct {
	ID       string // Unique rule identifier (e.g., "FIELD_NO_DELETE")
	Category string // Rule category: WIRE, SOURCE, or FILE
	Enabled  bool   // Whether this rule is active
}
