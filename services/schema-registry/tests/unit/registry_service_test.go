package services_test

import (
	"context"
	"testing"
	"time"

	"github.com/gstack/schema-registry-service/domain/models"
	"github.com/gstack/schema-registry-service/domain/services"
)

// --- Mock implementations for outbound ports ---

// mockSchemaRepository implements outbound.SchemaRepository for testing.
type mockSchemaRepository struct {
	schemas   map[int32]models.Schema
	bySubject map[string]map[int32]models.Schema
	nextID    int32
	saveErr   error
	findErr   error
}

func newMockSchemaRepository() *mockSchemaRepository {
	return &mockSchemaRepository{
		schemas:   make(map[int32]models.Schema),
		bySubject: make(map[string]map[int32]models.Schema),
		nextID:    1,
	}
}

func (m *mockSchemaRepository) Save(_ context.Context, schema models.Schema) (models.Schema, error) {
	if m.saveErr != nil {
		return models.Schema{}, m.saveErr
	}
	schema.ID = m.nextID
	m.nextID++
	if schema.RegisteredAt.IsZero() {
		schema.RegisteredAt = time.Now().UTC()
	}
	m.schemas[schema.ID] = schema
	if _, ok := m.bySubject[schema.Subject]; !ok {
		m.bySubject[schema.Subject] = make(map[int32]models.Schema)
	}
	m.bySubject[schema.Subject][schema.Version] = schema
	return schema, nil
}

func (m *mockSchemaRepository) FindBySubject(_ context.Context, subject string) ([]models.Schema, error) {
	if m.findErr != nil {
		return nil, m.findErr
	}
	versions, ok := m.bySubject[subject]
	if !ok {
		return []models.Schema{}, nil
	}
	result := make([]models.Schema, 0, len(versions))
	for _, s := range versions {
		result = append(result, s)
	}
	return result, nil
}

func (m *mockSchemaRepository) FindBySubjectAndVersion(_ context.Context, subject string, version int32) (*models.Schema, error) {
	if m.findErr != nil {
		return nil, m.findErr
	}
	versions, ok := m.bySubject[subject]
	if !ok {
		return nil, nil
	}
	schema, ok := versions[version]
	if !ok {
		return nil, nil
	}
	return &schema, nil
}

func (m *mockSchemaRepository) FindLatestBySubject(_ context.Context, subject string) (*models.Schema, error) {
	if m.findErr != nil {
		return nil, m.findErr
	}
	versions, ok := m.bySubject[subject]
	if !ok {
		return nil, nil
	}
	var latest *models.Schema
	for _, s := range versions {
		schema := s
		if latest == nil || schema.Version > latest.Version {
			latest = &schema
		}
	}
	return latest, nil
}

func (m *mockSchemaRepository) FindById(_ context.Context, schemaID int32) (*models.Schema, error) {
	if m.findErr != nil {
		return nil, m.findErr
	}
	schema, ok := m.schemas[schemaID]
	if !ok {
		return nil, nil
	}
	return &schema, nil
}

func (m *mockSchemaRepository) FindByFingerprint(_ context.Context, subject, fingerprint string) (*models.Schema, error) {
	versions, ok := m.bySubject[subject]
	if !ok {
		return nil, nil
	}
	for _, s := range versions {
		if s.Fingerprint == fingerprint {
			return &s, nil
		}
	}
	return nil, nil
}

func (m *mockSchemaRepository) DeleteSubject(_ context.Context, subject string, _ bool) error {
	delete(m.bySubject, subject)
	return nil
}

func (m *mockSchemaRepository) ListSubjects(_ context.Context, prefix string) ([]string, error) {
	subjects := make([]string, 0)
	for subject := range m.bySubject {
		if prefix != "" && len(subject) < len(prefix) {
			continue
		}
		if prefix != "" && subject[:len(prefix)] != prefix {
			continue
		}
		subjects = append(subjects, subject)
	}
	return subjects, nil
}

func (m *mockSchemaRepository) CountSubjects(_ context.Context, prefix string) (int64, error) {
	count := int64(0)
	for subject := range m.bySubject {
		if prefix != "" && (len(subject) < len(prefix) || subject[:len(prefix)] != prefix) {
			continue
		}
		count++
	}
	return count, nil
}

func (m *mockSchemaRepository) GetNextVersion(_ context.Context, subject string) (int32, error) {
	versions, ok := m.bySubject[subject]
	if !ok || len(versions) == 0 {
		return 1, nil
	}
	var maxVersion int32
	for _, s := range versions {
		if s.Version > maxVersion {
			maxVersion = s.Version
		}
	}
	return maxVersion + 1, nil
}

// --- RegistryService Tests ---

func TestRegistryService_Register_Success(t *testing.T) {
	repo := newMockSchemaRepository()
	svc := services.NewRegistryService(repo, nil, nil, nil, nil)

	resp, err := svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:          "order/v1/order.proto",
		Type:             models.SchemaTypeProtobuf,
		Definition:       `syntax = "proto3"; package order.v1;`,
		CompatibilityLvl: nil,
	})

	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if resp.SchemaID <= 0 {
		t.Errorf("expected positive schema ID, got %d", resp.SchemaID)
	}
	if resp.Version != 1 {
		t.Errorf("expected version 1, got %d", resp.Version)
	}
	if resp.Fingerprint == "" {
		t.Error("expected non-empty fingerprint")
	}
	if !resp.CompatibilityCheck.Compatible {
		t.Error("expected compatible (no previous version)")
	}
}

func TestRegistryService_Register_SecondVersion(t *testing.T) {
	repo := newMockSchemaRepository()
	svc := services.NewRegistryService(repo, nil, nil, nil, nil)

	// Register first version
	_, err := svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:    "order/v1/order.proto",
		Type:       models.SchemaTypeProtobuf,
		Definition: `syntax = "proto3"; package order.v1; message Order { string id = 1; }`,
	})
	if err != nil {
		t.Fatalf("first registration failed: %v", err)
	}

	// Register second version
	resp, err := svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:    "order/v1/order.proto",
		Type:       models.SchemaTypeProtobuf,
		Definition: `syntax = "proto3"; package order.v1; message Order { string id = 1; string name = 2; }`,
	})
	if err != nil {
		t.Fatalf("second registration failed: %v", err)
	}
	if resp.Version != 2 {
		t.Errorf("expected version 2, got %d", resp.Version)
	}
}

func TestRegistryService_Register_DuplicateFingerprint(t *testing.T) {
	repo := newMockSchemaRepository()
	svc := services.NewRegistryService(repo, nil, nil, nil, nil)

	def := `syntax = "proto3"; package order.v1;`

	// Register first
	resp1, err := svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:    "order/v1/order.proto",
		Type:       models.SchemaTypeProtobuf,
		Definition: def,
	})
	if err != nil {
		t.Fatalf("first registration failed: %v", err)
	}

	// Register same definition again
	resp2, err := svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:    "order/v1/order.proto",
		Type:       models.SchemaTypeProtobuf,
		Definition: def,
	})
	if err != nil {
		t.Fatalf("duplicate registration should not error, got: %v", err)
	}
	if resp2.SchemaID != resp1.SchemaID {
		t.Errorf("expected same schema ID for duplicate, got %d vs %d", resp2.SchemaID, resp1.SchemaID)
	}
	if resp2.Version != resp1.Version {
		t.Errorf("expected same version for duplicate, got %d vs %d", resp2.Version, resp1.Version)
	}
}

func TestRegistryService_Get_BySubjectAndVersion(t *testing.T) {
	repo := newMockSchemaRepository()
	svc := services.NewRegistryService(repo, nil, nil, nil, nil)

	// Register a schema
	registerResp, _ := svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:    "catalog/v1/catalog.proto",
		Type:       models.SchemaTypeProtobuf,
		Definition: `syntax = "proto3"; package catalog.v1;`,
	})

	// Retrieve by subject and version
	version := registerResp.Version
	resp, err := svc.Get(context.Background(), models.GetSchemaRequest{
		Subject: "catalog/v1/catalog.proto",
		Version: &version,
	})
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if resp.Schema.Subject != "catalog/v1/catalog.proto" {
		t.Errorf("expected subject 'catalog/v1/catalog.proto', got %q", resp.Schema.Subject)
	}
}

func TestRegistryService_Get_BySchemaID(t *testing.T) {
	repo := newMockSchemaRepository()
	svc := services.NewRegistryService(repo, nil, nil, nil, nil)

	registerResp, _ := svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:    "identity/v1/identity.proto",
		Type:       models.SchemaTypeProtobuf,
		Definition: `syntax = "proto3"; package identity.v1;`,
	})

	schemaID := registerResp.SchemaID
	resp, err := svc.Get(context.Background(), models.GetSchemaRequest{
		SchemaID: &schemaID,
	})
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if resp.Schema.ID != schemaID {
		t.Errorf("expected schema ID %d, got %d", schemaID, resp.Schema.ID)
	}
}

func TestRegistryService_Get_NotFound(t *testing.T) {
	repo := newMockSchemaRepository()
	svc := services.NewRegistryService(repo, nil, nil, nil, nil)

	_, err := svc.Get(context.Background(), models.GetSchemaRequest{
		Subject: "nonexistent/v1/none.proto",
	})
	if err == nil {
		t.Fatal("expected error for nonexistent subject, got nil")
	}
}

func TestRegistryService_Get_LatestVersion(t *testing.T) {
	repo := newMockSchemaRepository()
	svc := services.NewRegistryService(repo, nil, nil, nil, nil)

	// Register two versions
	svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:    "payment/v1/payment.proto",
		Type:       models.SchemaTypeProtobuf,
		Definition: `syntax = "proto3"; package payment.v1; message Payment { string id = 1; }`,
	})
	svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:    "payment/v1/payment.proto",
		Type:       models.SchemaTypeProtobuf,
		Definition: `syntax = "proto3"; package payment.v1; message Payment { string id = 1; int64 amount = 2; }`,
	})

	// Get latest without specifying version
	resp, err := svc.Get(context.Background(), models.GetSchemaRequest{
		Subject: "payment/v1/payment.proto",
	})
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if resp.Schema.Version != 2 {
		t.Errorf("expected latest version 2, got %d", resp.Schema.Version)
	}
}

func TestRegistryService_List(t *testing.T) {
	repo := newMockSchemaRepository()
	svc := services.NewRegistryService(repo, nil, nil, nil, nil)

	svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:    "order/v1/order.proto",
		Type:       models.SchemaTypeProtobuf,
		Definition: `syntax = "proto3"; package order.v1;`,
	})
	svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:    "catalog/v1/catalog.proto",
		Type:       models.SchemaTypeProtobuf,
		Definition: `syntax = "proto3"; package catalog.v1;`,
	})

	resp, err := svc.List(context.Background(), models.ListSchemasRequest{
		PageSize: 10,
	})
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if resp.TotalCount < 2 {
		t.Errorf("expected at least 2 subjects, got %d", resp.TotalCount)
	}
}

func TestRegistryService_Delete(t *testing.T) {
	repo := newMockSchemaRepository()
	svc := services.NewRegistryService(repo, nil, nil, nil, nil)

	svc.Register(context.Background(), models.RegisterSchemaRequest{
		Subject:    "to-delete/v1/test.proto",
		Type:       models.SchemaTypeProtobuf,
		Definition: `syntax = "proto3"; package test.v1;`,
	})

	err := svc.Delete(context.Background(), models.DeleteSubjectRequest{
		Subject:   "to-delete/v1/test.proto",
		Permanent: false,
		DeletedBy: "admin",
	})
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
}

// --- Model Tests ---

func TestSchemaType_String(t *testing.T) {
	tests := []struct {
		schemaType models.SchemaType
		want       string
	}{
		{models.SchemaTypeProtobuf, "PROTOBUF"},
		{models.SchemaTypeAvro, "AVRO"},
		{models.SchemaTypeJSONSchema, "JSON_SCHEMA"},
		{models.SchemaType(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.schemaType.String(); got != tt.want {
			t.Errorf("SchemaType(%d).String() = %q, want %q", tt.schemaType, got, tt.want)
		}
	}
}

func TestParseSchemaType(t *testing.T) {
	_, err := models.ParseSchemaType("PROTOBUF")
	if err != nil {
		t.Errorf("expected no error for PROTOBUF, got: %v", err)
	}
	_, err = models.ParseSchemaType("INVALID")
	if err == nil {
		t.Error("expected error for INVALID schema type")
	}
}

func TestCompatibilityLevel_String(t *testing.T) {
	tests := []struct {
		level models.CompatibilityLevel
		want  string
	}{
		{models.CompatibilityNone, "NONE"},
		{models.CompatibilityBackward, "BACKWARD"},
		{models.CompatibilityForward, "FORWARD"},
		{models.CompatibilityFull, "FULL"},
		{models.CompatibilityBackwardTransitive, "BACKWARD_TRANSITIVE"},
		{models.CompatibilityForwardTransitive, "FORWARD_TRANSITIVE"},
		{models.CompatibilityFullTransitive, "FULL_TRANSITIVE"},
	}

	for _, tt := range tests {
		if got := tt.level.String(); got != tt.want {
			t.Errorf("CompatibilityLevel(%d).String() = %q, want %q", tt.level, got, tt.want)
		}
	}
}

func TestCompatibilityLevel_IsBackward(t *testing.T) {
	if models.CompatibilityNone.IsBackward() {
		t.Error("NONE should not be backward")
	}
	if !models.CompatibilityBackward.IsBackward() {
		t.Error("BACKWARD should be backward")
	}
	if !models.CompatibilityFull.IsBackward() {
		t.Error("FULL should be backward")
	}
}

func TestCompatibilityLevel_IsForward(t *testing.T) {
	if models.CompatibilityNone.IsForward() {
		t.Error("NONE should not be forward")
	}
	if !models.CompatibilityForward.IsForward() {
		t.Error("FORWARD should be forward")
	}
	if !models.CompatibilityFull.IsForward() {
		t.Error("FULL should be forward")
	}
}

func TestCompatibilityLevel_IsTransitive(t *testing.T) {
	if models.CompatibilityBackward.IsTransitive() {
		t.Error("BACKWARD should not be transitive")
	}
	if !models.CompatibilityBackwardTransitive.IsTransitive() {
		t.Error("BACKWARD_TRANSITIVE should be transitive")
	}
}

func TestSchema_ComputeFingerprint(t *testing.T) {
	s1 := &models.Schema{Definition: "test definition"}
	s2 := &models.Schema{Definition: "test definition"}
	s3 := &models.Schema{Definition: "different definition"}

	fp1 := s1.ComputeFingerprint()
	fp2 := s2.ComputeFingerprint()
	fp3 := s3.ComputeFingerprint()

	if fp1 != fp2 {
		t.Error("identical definitions should produce the same fingerprint")
	}
	if fp1 == fp3 {
		t.Error("different definitions should produce different fingerprints")
	}
	if fp1 == "" {
		t.Error("fingerprint should not be empty")
	}
}

// --- Domain Error Tests ---

func TestSchemaIncompatibleError(t *testing.T) {
	err := &services.SchemaIncompatibleError{
		Subject: "order/v1/order.proto",
		Violations: []models.CompatibilityViolation{
			{Description: "field removed", Rule: "FIELD_NO_DELETE"},
		},
		Level: models.CompatibilityBackward,
	}
	if err.Error() == "" {
		t.Error("expected non-empty error message")
	}
}

func TestInvalidSchemaError(t *testing.T) {
	err := &services.InvalidSchemaError{
		Subject: "test.proto",
		Errors:  []models.ValidationError{{Message: "syntax error", RuleID: "SYNTAX"}},
	}
	if err.Error() == "" {
		t.Error("expected non-empty error message")
	}
}

func TestSchemaNotFoundError(t *testing.T) {
	v := int32(3)
	err := &services.SchemaNotFoundError{Subject: "missing.proto", Version: &v}
	if err.Error() == "" {
		t.Error("expected non-empty error message")
	}
}
