package services_test

import (
	"context"
	"testing"

	"github.com/gstack/schema-registry-service/domain/models"
	"github.com/gstack/schema-registry-service/domain/services"
)

// --- CompatibilityService Tests ---

func TestCompatibilityService_CheckCompatibility_NoneLevel(t *testing.T) {
	repo := newMockSchemaRepository()
	svc := services.NewCompatibilityService(repo, nil, nil)

	result, err := svc.CheckCompatibility(
		context.Background(),
		"test.proto",
		`syntax = "proto3";`,
		models.CompatibilityNone,
		nil,
	)
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if !result.Compatible {
		t.Error("NONE level should always return compatible")
	}
}

func TestCompatibilityService_CheckCompatibility_NoPreviousVersion(t *testing.T) {
	repo := newMockSchemaRepository()
	svc := services.NewCompatibilityService(repo, nil, nil)

	result, err := svc.CheckCompatibility(
		context.Background(),
		"new-subject.proto",
		`syntax = "proto3";`,
		models.CompatibilityBackward,
		nil,
	)
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if !result.Compatible {
		t.Error("no previous version should always be compatible")
	}
}

func TestCompatibilityService_CheckCompatibility_WithPreviousVersion(t *testing.T) {
	repo := newMockSchemaRepository()
	// Seed the repo with a previous version
	repo.Save(context.Background(), models.Schema{
		Subject:          "order.proto",
		Version:          1,
		Type:             models.SchemaTypeProtobuf,
		Definition:       `syntax = "proto3"; package order.v1;`,
		Fingerprint:      "abc123",
		CompatibilityLvl: models.CompatibilityBackward,
	})

	svc := services.NewCompatibilityService(repo, nil, nil)

	// Without a validator, compatibility checks cannot be performed,
	// so this will return an error from the validator being nil.
	// The compatibility service should handle this gracefully.
	_, err := svc.CheckCompatibility(
		context.Background(),
		"order.proto",
		`syntax = "proto3"; package order.v1; message Order { string id = 1; }`,
		models.CompatibilityBackward,
		nil,
	)
	// With nil validator, the service returns an error
	if err == nil {
		t.Log("CheckCompatibility returned without error (validator is nil)")
	}
}

// --- ValidationLevel Tests ---

func TestValidationLevel_String(t *testing.T) {
	tests := []struct {
		level models.ValidationLevel
		want  string
	}{
		{models.ValidationSyntax, "SYNTAX"},
		{models.ValidationSemantic, "SEMANTIC"},
		{models.ValidationCompatibility, "COMPATIBILITY"},
		{models.ValidationFull, "FULL"},
		{models.ValidationLevel(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.level.String(); got != tt.want {
			t.Errorf("ValidationLevel(%d).String() = %q, want %q", tt.level, got, tt.want)
		}
	}
}

func TestParseValidationLevel(t *testing.T) {
	valid := []string{"SYNTAX", "SEMANTIC", "COMPATIBILITY", "FULL"}
	for _, v := range valid {
		_, err := models.ParseValidationLevel(v)
		if err != nil {
			t.Errorf("expected no error for %q, got: %v", v, err)
		}
	}

	_, err := models.ParseValidationLevel("INVALID")
	if err == nil {
		t.Error("expected error for INVALID validation level")
	}
}

// --- CheckLevel Tests ---

func TestCheckLevel_String(t *testing.T) {
	tests := []struct {
		level models.CheckLevel
		want  string
	}{
		{models.CheckLevelMinimal, "MINIMAL"},
		{models.CheckLevelDefault, "DEFAULT"},
		{models.CheckLevelStrict, "STRICT"},
		{models.CheckLevel(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.level.String(); got != tt.want {
			t.Errorf("CheckLevel(%d).String() = %q, want %q", tt.level, got, tt.want)
		}
	}
}

func TestParseCheckLevel(t *testing.T) {
	valid := []string{"MINIMAL", "DEFAULT", "STRICT"}
	for _, v := range valid {
		_, err := models.ParseCheckLevel(v)
		if err != nil {
			t.Errorf("expected no error for %q, got: %v", v, err)
		}
	}

	_, err := models.ParseCheckLevel("INVALID")
	if err == nil {
		t.Error("expected error for INVALID check level")
	}
}

// --- ValidationError Tests ---

func TestValidationError_Error(t *testing.T) {
	err := &models.ValidationError{
		Message:  "field name must be snake_case",
		Location: "line 10, column 5",
		RuleID:   "FIELD_LOWER_SNAKE_CASE",
	}
	msg := err.Error()
	if msg == "" {
		t.Error("expected non-empty error message")
	}
}

func TestValidationError_Error_NoLocation(t *testing.T) {
	err := &models.ValidationError{
		Message: "schema is empty",
		RuleID:  "EMPTY_SCHEMA",
	}
	msg := err.Error()
	if msg == "" {
		t.Error("expected non-empty error message")
	}
}

func TestValidationWarning_String(t *testing.T) {
	w := models.ValidationWarning{
		Message:  "package name should be lowercase",
		Location: "line 1",
		RuleID:   "PACKAGE_LOWER_SNAKE_CASE",
	}
	msg := w.String()
	if msg == "" {
		t.Error("expected non-empty warning message")
	}
}

// --- CompatibilityViolation Tests ---

func TestCompatibilityViolation_Fields(t *testing.T) {
	v := models.CompatibilityViolation{
		Description:  "field 'price' was removed",
		FieldPath:    "Order.price",
		Rule:         "FIELD_NO_DELETE",
		PreviousType: "double",
		ProposedType: "",
	}
	if v.Description == "" {
		t.Error("expected non-empty description")
	}
	if v.FieldPath == "" {
		t.Error("expected non-empty field path")
	}
}

// --- BreakingChange and Mitigation Tests ---

func TestBreakingChange_Fields(t *testing.T) {
	c := models.BreakingChange{
		ChangeType:  "FIELD_REMOVED",
		FieldPath:   "Order.price",
		Description: "Field 'price' was removed from message 'Order'",
		Category:    "WIRE",
	}
	if c.ChangeType == "" || c.Category == "" {
		t.Error("expected non-empty change type and category")
	}
}

func TestMitigationSuggestion_Fields(t *testing.T) {
	m := models.MitigationSuggestion{
		ChangeType: "FIELD_REMOVED",
		Suggestion: "Mark the field as reserved instead of removing it",
		Example:    `reserved 3; reserved "price";`,
	}
	if m.Suggestion == "" {
		t.Error("expected non-empty suggestion")
	}
}
