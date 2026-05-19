package integration_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/comprehensive-architecture/services/gateway/adapters/inbound/rest"
	"github.com/comprehensive-architecture/services/gateway/adapters/outbound/discovery"
	"github.com/comprehensive-architecture/services/gateway/domain/models"
	"github.com/comprehensive-architecture/services/gateway/domain/services"
	"github.com/comprehensive-architecture/services/gateway/infrastructure/config"
)

// --- Integration test helpers ---

// testApp holds the initialized test application components.
type testApp struct {
	routerService *services.RouterService
	discovery     *discovery.KubernetesDiscovery
	controller    *rest.Controller
}

// newTestApp creates a test application with mock outbound adapters.
func newTestApp(t *testing.T) *testApp {
	t.Helper()

	// Create Kubernetes discovery adapter
	disc, err := discovery.NewKubernetesDiscovery(discovery.KubernetesConfig{
		Namespace:      "test",
		ResyncInterval: 10 * time.Second,
		InCluster:      false,
	}, nil)
	if err != nil {
		t.Fatalf("failed to create discovery adapter: %v", err)
	}

	// Seed with test endpoints
	disc.SetEndpoints("catalog", []models.ServiceEndpoint{
		{Name: "catalog", Host: "catalog-svc", Port: 8080, Protocol: "http", Healthy: true},
	})
	disc.SetEndpoints("order", []models.ServiceEndpoint{
		{Name: "order", Host: "order-svc", Port: 8080, Protocol: "grpc", Healthy: true},
		{Name: "order", Host: "order-svc-2", Port: 8080, Protocol: "grpc", Healthy: false},
	})
	disc.SetEndpoints("payment", []models.ServiceEndpoint{
		{Name: "payment", Host: "payment-svc", Port: 8080, Protocol: "grpc", Healthy: true},
	})

	// Create in-memory rate limiter (skip Redis for integration tests)
	limiter := &inMemoryRateLimiter{
		counters: make(map[string]int),
	}

	// Create routes
	routes := map[string]models.Route{
		"catalog-api": {
			ID:              "catalog-api",
			Pattern:         "/api/v1/catalog/*",
			Methods:         []string{"GET", "POST"},
			UpstreamService: "catalog",
			Timeout:         10 * time.Second,
			RateLimitPolicy: "default",
			Middleware:      []string{"logging", "ratelimit"},
		},
		"order-api": {
			ID:              "order-api",
			Pattern:         "/api/v1/orders/*",
			Methods:         []string{"GET", "POST", "PUT"},
			UpstreamService: "order",
			Timeout:         30 * time.Second,
			RateLimitPolicy: "strict",
			RequireAuth:     true,
			Middleware:      []string{"logging", "auth", "ratelimit"},
		},
		"payment-api": {
			ID:              "payment-api",
			Pattern:         "/api/v1/payments/*",
			Methods:         []string{"POST"},
			UpstreamService: "payment",
			Timeout:         15 * time.Second,
			RateLimitPolicy: "strict",
			RequireAuth:     true,
			Middleware:      []string{"logging", "auth", "ratelimit"},
		},
	}

	policies := map[string]models.RateLimitPolicy{
		"default": {
			Name:           "default",
			RequestsPerSec: 100,
			BurstSize:      200,
			Window:         60 * time.Second,
			KeyTemplate:    "{{.ClientID}}:{{.Route}}",
		},
		"strict": {
			Name:           "strict",
			RequestsPerSec: 10,
			BurstSize:      20,
			Window:         60 * time.Second,
			KeyTemplate:    "{{.ClientID}}:{{.Route}}",
		},
	}

	routerService := services.NewRouterService(disc, limiter, routes, policies, nil)
	controller := rest.NewController(routerService, routerService, routerService, routerService, nil)

	return &testApp{
		routerService: routerService,
		discovery:     disc,
		controller:    controller,
	}
}

// inMemoryRateLimiter is a simple in-memory rate limiter for integration tests.
type inMemoryRateLimiter struct {
	counters map[string]int
}

func (m *inMemoryRateLimiter) Allow(_ context.Context, key string, policy models.RateLimitPolicy) (models.RateLimitStatus, error) {
	m.counters[key]++
	count := m.counters[key]
	allowed := count <= policy.BurstSize
	remaining := policy.BurstSize - count
	if remaining < 0 {
		remaining = 0
	}
	var retryAfter time.Duration
	if !allowed && policy.RequestsPerSec > 0 {
		retryAfter = time.Duration(float64(time.Second) / policy.RequestsPerSec)
	}
	return models.RateLimitStatus{
		Key:        key,
		Allowed:    allowed,
		Remaining:  remaining,
		Limit:      policy.BurstSize,
		ResetAt:    time.Now().Add(policy.Window),
		Policy:     policy.Name,
		RetryAfter: retryAfter,
	}, nil
}

func (m *inMemoryRateLimiter) GetStatus(_ context.Context, key string, policy models.RateLimitPolicy) (models.RateLimitStatus, error) {
	count := m.counters[key]
	remaining := policy.BurstSize - count
	if remaining < 0 {
		remaining = 0
	}
	return models.RateLimitStatus{
		Key:       key,
		Allowed:   remaining > 0,
		Remaining: remaining,
		Limit:     policy.BurstSize,
		ResetAt:   time.Now().Add(policy.Window),
		Policy:    policy.Name,
	}, nil
}

func (m *inMemoryRateLimiter) Reset(_ context.Context, key string) error {
	delete(m.counters, key)
	return nil
}

// --- Integration Tests ---

func TestIntegration_HealthCheckEndpoint(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/gateway/health", nil)
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
}

func TestIntegration_GetRateLimitEndpoint(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/gateway/rate-limit/test-client?route=catalog-api", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d; body: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	if resp["allowed"] != true {
		t.Errorf("expected allowed=true, got %v", resp["allowed"])
	}
}

func TestIntegration_GetRateLimitEndpoint_MissingClientID(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/gateway/rate-limit/", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	// Should return 404 since the path doesn't match the pattern
	if w.Code == http.StatusOK {
		t.Error("expected non-200 status for missing clientID")
	}
}

func TestIntegration_GetRouteConfigEndpoint(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/gateway/routes/catalog", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d; body: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	routes, ok := resp["routes"].([]interface{})
	if !ok {
		t.Fatal("expected 'routes' to be an array")
	}
	if len(routes) != 1 {
		t.Errorf("expected 1 route, got %d", len(routes))
	}
}

func TestIntegration_GetRouteConfigEndpoint_NotFound(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/gateway/routes/nonexistent", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusNotFound {
		t.Errorf("expected status 404, got %d", w.Code)
	}
}

func TestIntegration_RouteProxyEndpoint(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	body := `{"query": "laptops"}`
	req := httptest.NewRequest(http.MethodGet, "/api/v1/catalog/products", strings.NewReader(body))
	req.Header.Set("X-API-Key", "test-client")
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	// The route should match and return 200 (the domain service returns 200)
	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d; body: %s", w.Code, w.Body.String())
	}
}

func TestIntegration_RouteProxyEndpoint_NotFound(t *testing.T) {
	app := newTestApp(t)
	handler := app.controller.Handler()

	req := httptest.NewRequest(http.MethodGet, "/unknown/path", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusInternalServerError {
		t.Errorf("expected status 500, got %d", w.Code)
	}
}

func TestIntegration_HealthCheckAggregatesDownstream(t *testing.T) {
	app := newTestApp(t)

	// Make the order service have a degraded endpoint
	app.discovery.SetEndpoints("order", []models.ServiceEndpoint{
		{Name: "order", Host: "order-svc", Port: 8080, Protocol: "grpc", Healthy: false},
	})

	resp := app.routerService.HealthCheck(context.Background(), models.HealthCheckRequest{})

	// With one service fully unhealthy, overall should be degraded
	if resp.Status != models.StatusDegraded {
		t.Errorf("expected DEGRADED overall status, got %v", resp.Status)
	}

	// Find the order downstream entry
	var orderHealth *models.DownstreamHealth
	for i := range resp.Downstream {
		if resp.Downstream[i].Service == "order" {
			orderHealth = &resp.Downstream[i]
			break
		}
	}
	if orderHealth == nil {
		t.Fatal("order downstream entry not found")
	}
	if orderHealth.Status != models.StatusNotServing {
		t.Errorf("expected order NOT_SERVING, got %v", orderHealth.Status)
	}
}

func TestIntegration_CORSHeaders(t *testing.T) {
	app := newTestApp(t)
	handler := rest.CORSMiddleware([]string{"https://example.com"})(app.controller.Handler())

	// Test preflight
	req := httptest.NewRequest(http.MethodOptions, "/api/v1/gateway/health", nil)
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

// Test the full request lifecycle through middleware
func TestIntegration_FullMiddlewareStack(t *testing.T) {
	app := newTestApp(t)

	// Build the full middleware stack
	handler := app.controller.Handler()
	handler = rest.CORSMiddleware(nil)(handler)
	handler = rest.RecoveryMiddleware(nil)(handler)
	handler = rest.LoggingMiddleware(nil)(handler)

	// Test a normal request
	req := httptest.NewRequest(http.MethodGet, "/api/v1/gateway/health", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", w.Code)
	}

	// Verify JSON content type
	contentType := w.Header().Get("Content-Type")
	if !strings.Contains(contentType, "application/json") {
		t.Errorf("expected JSON content type, got %q", contentType)
	}
}
