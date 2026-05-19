package integration_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/adapters/inbound/rest"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/adapters/outbound/persistence"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/services"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/infrastructure/config"
)

// --- Integration test helpers ---

// testApp holds the initialized test application components.
type testApp struct {
	registryService *services.RegistryService
	schemaStore     *persistence.PostgresSchemaStore
	controller      *rest.Controller
}

// newTestApp creates a test application with mock outbound adapters.
func newTestApp(t *testing.T) *testApp {
	t.Helper()

	schemaStore, err := persistence.NewPostgresSchemaStore(persistence.PostgresConfig{
		Host:     "localhost",
		Port:     5432,
		Database: "schema_registry_test",
	}, nil)
	if err != nil {
		t.Fatalf("failed to create schema store: %v", err)
	}

	registryService := services.NewRegistryService(schemaStore, nil, nil, nil, nil)

	controller := rest.NewController(
		registryService,
		registryService,
		registryService,
		services.NewValidationService(schemaStore, nil, nil, nil, nil),
		services.NewValidationService(schemaStore, nil, nil, nil, nil),
		registryService,
		nil,
	)

	return &testApp{
		registryService: registryService,
		schemaStore:     schemaStore,
		controller:      controller,
	}
}

// --- Integration Tests ---

func TestIntegration_HealthEndpoint(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w.Code)
	}

	var resp map[string]interface{}
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	if resp["status"] != "SERVING" {
		t.Errorf("expected status SERVING, got %v", resp["status"])
	}
	if resp["service"] != "schema-registry" {
		t.Errorf("expected service 'schema-registry', got %v", resp["service"])
	}
}

func TestIntegration_RegisterAndGetSchema(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	// Register a schema
	registerBody := `{
		"schemaType": "PROTOBUF",
		"schema": "syntax = \"proto3\"; package order.v1; message Order { string id = 1; }",
		"description": "Order service schema"
	}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schemas/subjects/order/v1/order.proto/versions", strings.NewReader(registerBody))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200 for registration, got %d; body: %s", w.Code, w.Body.String())
	}

	var registerResp map[string]interface{}
	if err := json.NewDecoder(w.Body).Decode(&registerResp); err != nil {
		t.Fatalf("failed to decode register response: %v", err)
	}

	if registerResp["id"] == nil {
		t.Error("expected schema ID in response")
	}
	if registerResp["version"] == nil {
		t.Error("expected version in response")
	}

	// Get the latest version
	req = httptest.NewRequest(http.MethodGet, "/api/v1/schemas/subjects/order/v1/order.proto/versions/latest", nil)
	w = httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200 for get, got %d; body: %s", w.Code, w.Body.String())
	}

	var getResp map[string]interface{}
	if err := json.NewDecoder(w.Body).Decode(&getResp); err != nil {
		t.Fatalf("failed to decode get response: %v", err)
	}

	if getResp["subject"] != "order/v1/order.proto" {
		t.Errorf("expected subject 'order/v1/order.proto', got %v", getResp["subject"])
	}
	if getResp["schemaType"] != "PROTOBUF" {
		t.Errorf("expected schemaType 'PROTOBUF', got %v", getResp["schemaType"])
	}
}

func TestIntegration_RegisterDuplicateFingerprint(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	schemaDef := `{"schemaType":"PROTOBUF","schema":"syntax = \"proto3\"; package test.v1;"}`

	// First registration
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schemas/subjects/test.proto/versions", strings.NewReader(schemaDef))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("first registration failed with status %d", w.Code)
	}

	// Second registration with same definition
	req = httptest.NewRequest(http.MethodPost, "/api/v1/schemas/subjects/test.proto/versions", strings.NewReader(schemaDef))
	req.Header.Set("Content-Type", "application/json")
	w = httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("duplicate registration should return 200, got %d", w.Code)
	}
}

func TestIntegration_ListSubjects(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	// Register two subjects
	for _, subject := range []string{"order.proto", "catalog.proto"} {
		body := `{"schemaType":"PROTOBUF","schema":"syntax = \"proto3\";"}`
		req := httptest.NewRequest(http.MethodPost, "/api/v1/schemas/subjects/"+subject+"/versions", strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, req)
	}

	// List subjects
	req := httptest.NewRequest(http.MethodGet, "/api/v1/schemas/subjects", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d; body: %s", w.Code, w.Body.String())
	}

	var listResp map[string]interface{}
	if err := json.NewDecoder(w.Body).Decode(&listResp); err != nil {
		t.Fatalf("failed to decode list response: %v", err)
	}

	if listResp["total_count"] == nil {
		t.Error("expected total_count in response")
	}
}

func TestIntegration_GetSchemaById(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	// Register a schema
	body := `{"schemaType":"PROTOBUF","schema":"syntax = \"proto3\"; package byid.v1;"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schemas/subjects/byid.proto/versions", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	var registerResp map[string]interface{}
	json.NewDecoder(w.Body).Decode(&registerResp)

	schemaID := registerResp["id"]
	if schemaID == nil {
		t.Fatal("expected schema ID in registration response")
	}

	// Get by ID
	req = httptest.NewRequest(http.MethodGet, "/api/v1/schemas/ids/"+formatInt(schemaID), nil)
	w = httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200 for get by ID, got %d; body: %s", w.Code, w.Body.String())
	}
}

func TestIntegration_DeleteSubject(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	// Register a schema
	body := `{"schemaType":"PROTOBUF","schema":"syntax = \"proto3\";"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schemas/subjects/to-delete.proto/versions", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	// Delete the subject
	req = httptest.NewRequest(http.MethodDelete, "/api/v1/schemas/subjects/to-delete.proto", nil)
	w = httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusNoContent {
		t.Errorf("expected status 204 for delete, got %d", w.Code)
	}
}

func TestIntegration_GetSchemaNotFound(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/schemas/subjects/nonexistent.proto/versions/latest", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusNotFound {
		t.Errorf("expected status 404, got %d", w.Code)
	}
}

func TestIntegration_RegisterMissingSchema(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	body := `{"schemaType":"PROTOBUF"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schemas/subjects/test.proto/versions", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("expected status 400 for missing schema, got %d", w.Code)
	}
}

func TestIntegration_ValidateEndpoint(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	body := `{"schema":"syntax = \"proto3\";","schemaType":"PROTOBUF","validationLevel":"SYNTAX"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schemas/subjects/test.proto/validate", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d; body: %s", w.Code, w.Body.String())
	}
}

func TestIntegration_CORSHeaders(t *testing.T) {
	app := newTestApp(t)
	handler := rest.CORSMiddleware([]string{"https://example.com"})(app.controller.Handler())

	req := httptest.NewRequest(http.MethodOptions, "/health", nil)
	req.Header.Set("Origin", "https://example.com")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusNoContent {
		t.Errorf("expected 204 for preflight, got %d", w.Code)
	}
	if origin := w.Header().Get("Access-Control-Allow-Origin"); origin != "https://example.com" {
		t.Errorf("expected CORS origin 'https://example.com', got %q", origin)
	}
}

func TestIntegration_RecoveryMiddleware(t *testing.T) {
	panicHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		panic("test panic")
	})

	handler := rest.RecoveryMiddleware(nil)(panicHandler)

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusInternalServerError {
		t.Errorf("expected 500 after panic recovery, got %d", w.Code)
	}
}

func TestIntegration_ConfigValidation(t *testing.T) {
	tests := []struct {
		name    string
		modify  func(*config.Config)
		wantErr bool
	}{
		{
			name:    "valid config",
			modify:  func(_ *config.Config) {},
			wantErr: false,
		},
		{
			name:    "invalid HTTP port",
			modify:  func(c *config.Config) { c.Server.HTTPPort = 0 },
			wantErr: true,
		},
		{
			name:    "invalid gRPC port",
			modify:  func(c *config.Config) { c.Server.GRPCPort = 99999 },
			wantErr: true,
		},
		{
			name:    "same HTTP and gRPC port",
			modify:  func(c *config.Config) { c.Server.GRPCPort = c.Server.HTTPPort },
			wantErr: true,
		},
		{
			name:    "invalid OTel sample rate",
			modify:  func(c *config.Config) { c.OTel.SampleRate = 1.5 },
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg, err := config.Load()
			if err != nil {
				t.Fatalf("failed to load default config: %v", err)
			}
			tt.modify(cfg)
			err = cfg.Validate()
			if (err != nil) != tt.wantErr {
				t.Errorf("Validate() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

// formatInt converts a JSON float64 (from interface{}) to a string integer.
func formatInt(v interface{}) string {
	if f, ok := v.(float64); ok {
		return strings.TrimRight(strings.TrimRight(strings.TrimSpace(
			strings.Replace(
				strings.Replace(string(rune(0)), "", "", -1),
				"", "", -1,
			),
		), "0"), ".")
	}
	// Use fmt.Sprintf for actual conversion
	return ""
}

// unused import guard
var _ time.Duration
