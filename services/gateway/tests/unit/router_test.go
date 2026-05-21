package services_test

import (
	"context"
	"testing"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/ports/outbound"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/services"
)

// --- Mock implementations for outbound ports ---

// mockServiceDiscovery implements outbound.ServiceDiscoveryPort for testing.
type mockServiceDiscovery struct {
	services   map[string][]models.ServiceEndpoint
	listErr    error
	resolveErr error
}

func (m *mockServiceDiscovery) Resolve(_ context.Context, serviceName string) ([]models.ServiceEndpoint, error) {
	if m.resolveErr != nil {
		return nil, m.resolveErr
	}
	endpoints, ok := m.services[serviceName]
	if !ok {
		return nil, &services.UpstreamUnavailableError{Service: serviceName, Message: "not found"}
	}
	return endpoints, nil
}

func (m *mockServiceDiscovery) Watch(_ context.Context, _ string) (<-chan outbound.EndpointChange, error) {
	return nil, nil
}

func (m *mockServiceDiscovery) ListServices(_ context.Context) ([]string, error) {
	if m.listErr != nil {
		return nil, m.listErr
	}
	names := make([]string, 0, len(m.services))
	for name := range m.services {
		names = append(names, name)
	}
	return names, nil
}

// mockRateLimiter implements outbound.RateLimiterPort for testing.
type mockRateLimiter struct {
	allowErr    error
	status      models.RateLimitStatus
	allowCalled bool
	resetCalled bool
}

func (m *mockRateLimiter) Allow(_ context.Context, _ string, _ models.RateLimitPolicy) (models.RateLimitStatus, error) {
	m.allowCalled = true
	if m.allowErr != nil {
		return models.RateLimitStatus{}, m.allowErr
	}
	return m.status, nil
}

func (m *mockRateLimiter) GetStatus(_ context.Context, _ string, _ models.RateLimitPolicy) (models.RateLimitStatus, error) {
	return m.status, nil
}

func (m *mockRateLimiter) Reset(_ context.Context, _ string) error {
	m.resetCalled = true
	return nil
}

// --- Tests ---

func TestRouterService_Route_Success(t *testing.T) {
	routes := map[string]models.Route{
		"catalog-api": {
			ID:              "catalog-api",
			Pattern:         "/api/v1/catalog/*",
			Methods:         []string{"GET", "POST"},
			UpstreamService: "catalog",
			Timeout:         10 * time.Second,
		},
	}

	discovery := &mockServiceDiscovery{
		services: map[string][]models.ServiceEndpoint{
			"catalog": {
				{Name: "catalog", Host: "catalog-svc", Port: 8080, Protocol: "grpc", Healthy: true},
			},
		},
	}

	limiter := &mockRateLimiter{
		status: models.RateLimitStatus{Allowed: true, Remaining: 100},
	}

	svc := services.NewRouterService(discovery, limiter, routes, nil, nil)

	resp, err := svc.Route(context.Background(), models.RouteRequest{
		Method:  "GET",
		Path:    "/api/v1/catalog/products",
		Headers: map[string]string{"X-API-Key": "test-client"},
		Body:    []byte("{}"),
	})

	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if resp.UpstreamService != "catalog" {
		t.Errorf("expected upstream service 'catalog', got %q", resp.UpstreamService)
	}
	if resp.Status != 200 {
		t.Errorf("expected status 200, got %d", resp.Status)
	}
}

func TestRouterService_Route_NotFound(t *testing.T) {
	routes := map[string]models.Route{}

	discovery := &mockServiceDiscovery{services: map[string][]models.ServiceEndpoint{}}
	limiter := &mockRateLimiter{status: models.RateLimitStatus{Allowed: true, Remaining: 100}}

	svc := services.NewRouterService(discovery, limiter, routes, nil, nil)

	_, err := svc.Route(context.Background(), models.RouteRequest{
		Method: "GET",
		Path:   "/unknown",
	})

	if err == nil {
		t.Fatal("expected error for unknown route, got nil")
	}
}

func TestRouterService_Route_RateLimitExceeded(t *testing.T) {
	routes := map[string]models.Route{
		"strict-api": {
			ID:              "strict-api",
			Pattern:         "/api/v1/strict/*",
			Methods:         []string{"GET"},
			UpstreamService: "backend",
			RateLimitPolicy: "strict",
		},
	}

	policies := map[string]models.RateLimitPolicy{
		"strict": {
			Name:           "strict",
			RequestsPerSec: 10,
			BurstSize:      20,
			Window:         60 * time.Second,
			KeyTemplate:    "{{.ClientID}}:{{.Route}}",
		},
	}

	discovery := &mockServiceDiscovery{
		services: map[string][]models.ServiceEndpoint{
			"backend": {{Name: "backend", Host: "backend-svc", Port: 8080, Healthy: true}},
		},
	}

	limiter := &mockRateLimiter{
		status: models.RateLimitStatus{
			Allowed:    false,
			Remaining:  0,
			Policy:     "strict",
			RetryAfter: 5 * time.Second,
			ResetAt:    time.Now().Add(5 * time.Second),
		},
	}

	svc := services.NewRouterService(discovery, limiter, routes, policies, nil)

	_, err := svc.Route(context.Background(), models.RouteRequest{
		Method:  "GET",
		Path:    "/api/v1/strict/resource",
		Headers: map[string]string{"X-API-Key": "test-client"},
	})

	if err == nil {
		t.Fatal("expected rate limit error, got nil")
	}

	rle, ok := err.(*services.RateLimitError)
	if !ok {
		t.Fatalf("expected *RateLimitError, got %T: %v", err, err)
	}
	if rle.Policy != "strict" {
		t.Errorf("expected policy 'strict', got %q", rle.Policy)
	}
	if rle.RetryAfter != 5*time.Second {
		t.Errorf("expected retry_after 5s, got %s", rle.RetryAfter)
	}
}

func TestRouterService_Route_UpstreamUnavailable(t *testing.T) {
	routes := map[string]models.Route{
		"catalog-api": {
			ID:              "catalog-api",
			Pattern:         "/api/v1/catalog/*",
			UpstreamService: "catalog",
		},
	}

	discovery := &mockServiceDiscovery{
		services: map[string][]models.ServiceEndpoint{
			"catalog": {}, // No healthy endpoints
		},
	}

	limiter := &mockRateLimiter{status: models.RateLimitStatus{Allowed: true, Remaining: 100}}

	svc := services.NewRouterService(discovery, limiter, routes, nil, nil)

	_, err := svc.Route(context.Background(), models.RouteRequest{
		Method: "GET",
		Path:   "/api/v1/catalog/products",
	})

	if err == nil {
		t.Fatal("expected upstream unavailable error, got nil")
	}

	uue, ok := err.(*services.UpstreamUnavailableError)
	if !ok {
		t.Fatalf("expected *UpstreamUnavailableError, got %T: %v", err, err)
	}
	if uue.Service != "catalog" {
		t.Errorf("expected service 'catalog', got %q", uue.Service)
	}
}

func TestRouterService_HealthCheck_Serving(t *testing.T) {
	discovery := &mockServiceDiscovery{
		services: map[string][]models.ServiceEndpoint{
			"catalog": {{Name: "catalog", Host: "catalog-svc", Port: 8080, Healthy: true}},
			"order":   {{Name: "order", Host: "order-svc", Port: 8080, Healthy: true}},
		},
	}

	limiter := &mockRateLimiter{}
	svc := services.NewRouterService(discovery, limiter, nil, nil, nil)

	resp := svc.HealthCheck(context.Background(), models.HealthCheckRequest{})

	if resp.Status != models.StatusServing {
		t.Errorf("expected SERVING, got %v", resp.Status)
	}
	if len(resp.Downstream) != 2 {
		t.Errorf("expected 2 downstream entries, got %d", len(resp.Downstream))
	}
}

func TestRouterService_HealthCheck_Degraded(t *testing.T) {
	discovery := &mockServiceDiscovery{
		services: map[string][]models.ServiceEndpoint{
			"catalog": {{Name: "catalog", Host: "catalog-svc", Port: 8080, Healthy: false}},
		},
	}

	limiter := &mockRateLimiter{}
	svc := services.NewRouterService(discovery, limiter, nil, nil, nil)

	resp := svc.HealthCheck(context.Background(), models.HealthCheckRequest{})

	if resp.Status != models.StatusDegraded {
		t.Errorf("expected DEGRADED, got %v", resp.Status)
	}
}

func TestRouterService_HealthCheck_DiscoveryFailure(t *testing.T) {
	discovery := &mockServiceDiscovery{
		services: map[string][]models.ServiceEndpoint{},
		listErr:  context.DeadlineExceeded,
	}

	limiter := &mockRateLimiter{}
	svc := services.NewRouterService(discovery, limiter, nil, nil, nil)

	resp := svc.HealthCheck(context.Background(), models.HealthCheckRequest{})

	// Health check should never error — it should return a degraded response
	if resp.Status != models.StatusDegraded {
		t.Errorf("expected DEGRADED on discovery failure, got %v", resp.Status)
	}
}

func TestRouterService_GetRateLimit(t *testing.T) {
	routes := map[string]models.Route{
		"catalog-api": {
			ID:              "catalog-api",
			Pattern:         "/api/v1/catalog/*",
			RateLimitPolicy: "default",
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
	}

	discovery := &mockServiceDiscovery{services: map[string][]models.ServiceEndpoint{}}
	limiter := &mockRateLimiter{
		status: models.RateLimitStatus{
			Allowed:   true,
			Remaining: 95,
			Policy:    "default",
			ResetAt:   time.Now().Add(30 * time.Second),
		},
	}

	svc := services.NewRouterService(discovery, limiter, routes, policies, nil)

	resp, err := svc.GetRateLimit(context.Background(), models.RateLimitRequest{
		ClientID: "test-client",
		Route:    "/api/v1/catalog/products",
	})

	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if !resp.Allowed {
		t.Error("expected allowed=true")
	}
	if resp.Remaining != 95 {
		t.Errorf("expected remaining=95, got %d", resp.Remaining)
	}
	if resp.Policy != "default" {
		t.Errorf("expected policy='default', got %q", resp.Policy)
	}
}

func TestRouterService_GetRouteConfig(t *testing.T) {
	routes := map[string]models.Route{
		"catalog-api": {
			ID:              "catalog-api",
			Pattern:         "/api/v1/catalog/*",
			UpstreamService: "catalog",
			Methods:         []string{"GET", "POST"},
			Timeout:         10 * time.Second,
			Middleware:      []string{"logging", "ratelimit"},
		},
		"order-api": {
			ID:              "order-api",
			Pattern:         "/api/v1/orders/*",
			UpstreamService: "order",
			Methods:         []string{"GET", "POST"},
			Timeout:         30 * time.Second,
			Middleware:      []string{"logging", "auth"},
		},
	}

	discovery := &mockServiceDiscovery{services: map[string][]models.ServiceEndpoint{}}
	limiter := &mockRateLimiter{}

	svc := services.NewRouterService(discovery, limiter, routes, nil, nil)

	// Test filtering by service name
	resp, err := svc.GetRouteConfig(context.Background(), models.RouteConfigRequest{
		ServiceName: "catalog",
	})

	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if len(resp.Routes) != 1 {
		t.Fatalf("expected 1 route, got %d", len(resp.Routes))
	}
	if resp.Routes[0].UpstreamService != "catalog" {
		t.Errorf("expected upstream 'catalog', got %q", resp.Routes[0].UpstreamService)
	}

	// Test all services
	resp, err = svc.GetRouteConfig(context.Background(), models.RouteConfigRequest{})
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if len(resp.Routes) != 2 {
		t.Errorf("expected 2 routes, got %d", len(resp.Routes))
	}

	// Test not found
	_, err = svc.GetRouteConfig(context.Background(), models.RouteConfigRequest{
		ServiceName: "nonexistent",
	})
	if err == nil {
		t.Error("expected error for nonexistent service, got nil")
	}
}

func TestRoute_MatchesMethod(t *testing.T) {
	tests := []struct {
		name    string
		methods []string
		method  string
		want    bool
	}{
		{"empty matches all", []string{}, "GET", true},
		{"exact match", []string{"GET", "POST"}, "GET", true},
		{"no match", []string{"POST"}, "GET", false},
		{"wildcard", []string{"*"}, "DELETE", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := models.Route{Methods: tt.methods}
			if got := r.MatchesMethod(tt.method); got != tt.want {
				t.Errorf("MatchesMethod() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestServiceEndpoint_Address(t *testing.T) {
	ep := models.ServiceEndpoint{Host: "catalog-svc", Port: 8080}
	if ep.Address() != "catalog-svc:8080" {
		t.Errorf("expected 'catalog-svc:8080', got %q", ep.Address())
	}
}

func TestServiceEndpoint_IsGRPC(t *testing.T) {
	ep := models.ServiceEndpoint{Protocol: "grpc"}
	if !ep.IsGRPC() {
		t.Error("expected IsGRPC=true for grpc protocol")
	}
	ep.Protocol = "http"
	if ep.IsGRPC() {
		t.Error("expected IsGRPC=false for http protocol")
	}
}

func TestServingStatus_String(t *testing.T) {
	tests := []struct {
		status models.ServingStatus
		want   string
	}{
		{models.StatusUnknown, "UNKNOWN"},
		{models.StatusServing, "SERVING"},
		{models.StatusNotServing, "NOT_SERVING"},
		{models.StatusDegraded, "DEGRADED"},
		{models.ServingStatus(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.status.String(); got != tt.want {
			t.Errorf("ServingStatus(%d).String() = %q, want %q", tt.status, got, tt.want)
		}
	}
}

func TestRateLimitError_Error(t *testing.T) {
	err := &services.RateLimitError{
		Key:        "test-key",
		Policy:     "strict",
		RetryAfter: 5 * time.Second,
	}
	msg := err.Error()
	if msg == "" {
		t.Error("expected non-empty error message")
	}
}

func TestUpstreamUnavailableError_Error(t *testing.T) {
	err := &services.UpstreamUnavailableError{
		Service: "catalog",
		Message: "no healthy endpoints",
	}
	msg := err.Error()
	if msg == "" {
		t.Error("expected non-empty error message")
	}
}
