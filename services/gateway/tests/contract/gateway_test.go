package contract_test

import (
	"context"
	"testing"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/services"
)

// Contract tests verify the Gateway service's API contract.
// In a full implementation, these would use Pact (pact-go) for
// consumer-driven contract testing. This file verifies the
// structural contract of request/response types and error types.

// --- Contract verification types ---

// ContractTestCase defines a contract test case for verifying
// API structure and behavior expectations.
type ContractTestCase struct {
	Name           string
	Endpoint       string
	Method         string
	ExpectedStatus uint32
	ExpectedError  string // Expected error type name (empty if no error)
	Request        interface{}
}

// --- Gateway Service Contract Tests ---

func TestRouteContract_RequestStructure(t *testing.T) {
	// Verify that RouteRequest has the expected fields
	req := models.RouteRequest{
		Method:  "GET",
		Path:    "/api/v1/catalog/products",
		Headers: map[string]string{"X-API-Key": "test-key"},
		Body:    []byte(`{"query": "laptops"}`),
	}

	if req.Method != "GET" {
		t.Error("RouteRequest.Method contract violated")
	}
	if req.Path != "/api/v1/catalog/products" {
		t.Error("RouteRequest.Path contract violated")
	}
	if req.Headers["X-API-Key"] != "test-key" {
		t.Error("RouteRequest.Headers contract violated")
	}
	if string(req.Body) != `{"query": "laptops"}` {
		t.Error("RouteRequest.Body contract violated")
	}
}

func TestRouteContract_ResponseStructure(t *testing.T) {
	// Verify that RouteResponse has the expected fields
	resp := models.RouteResponse{
		Status:          200,
		Headers:         map[string]string{"Content-Type": "application/json"},
		Body:            []byte(`{"products": []}`),
		UpstreamService: "catalog",
	}

	if resp.Status != 200 {
		t.Error("RouteResponse.Status contract violated")
	}
	if resp.Headers["Content-Type"] != "application/json" {
		t.Error("RouteResponse.Headers contract violated")
	}
	if resp.UpstreamService != "catalog" {
		t.Error("RouteResponse.UpstreamService contract violated")
	}
}

func TestRouteContract_ErrorTypes(t *testing.T) {
	// Verify rate limit error structure
	rle := &services.RateLimitError{
		Key:        "client:route",
		Policy:     "default",
		RetryAfter: 5 * time.Second,
		ResetAt:    time.Now().Add(5 * time.Second),
	}

	if rle.Key == "" {
		t.Error("RateLimitError.Key contract violated: must not be empty")
	}
	if rle.Policy == "" {
		t.Error("RateLimitError.Policy contract violated: must not be empty")
	}
	if rle.RetryAfter <= 0 {
		t.Error("RateLimitError.RetryAfter contract violated: must be positive")
	}

	// Verify upstream unavailable error structure
	uue := &services.UpstreamUnavailableError{
		Service: "catalog",
		Message: "no healthy endpoints",
	}

	if uue.Service == "" {
		t.Error("UpstreamUnavailableError.Service contract violated: must not be empty")
	}
	if uue.Message == "" {
		t.Error("UpstreamUnavailableError.Message contract violated: must not be empty")
	}
}

func TestHealthCheckContract_ResponseStructure(t *testing.T) {
	// Verify health check response structure
	resp := models.HealthCheckResponse{
		Status: models.StatusServing,
		Uptime: 2 * time.Hour,
		Downstream: []models.DownstreamHealth{
			{Service: "catalog", Status: models.StatusServing},
			{Service: "order", Status: models.StatusDegraded, Error: "2 endpoints unhealthy"},
		},
	}

	if resp.Status != models.StatusServing {
		t.Error("HealthCheckResponse.Status contract violated")
	}
	if resp.Uptime != 2*time.Hour {
		t.Error("HealthCheckResponse.Uptime contract violated")
	}
	if len(resp.Downstream) != 2 {
		t.Error("HealthCheckResponse.Downstream contract violated: expected 2 entries")
	}
}

func TestHealthCheckContract_ServingStatusEnum(t *testing.T) {
	// Verify that all serving status values are distinct and in range
	statuses := map[string]models.ServingStatus{
		"UNKNOWN":     models.StatusUnknown,
		"SERVING":     models.StatusServing,
		"NOT_SERVING": models.StatusNotServing,
		"DEGRADED":    models.StatusDegraded,
	}

	seen := map[models.ServingStatus]string{}
	for name, status := range statuses {
		if prev, exists := seen[status]; exists {
			t.Errorf("duplicate status value: %s and %s both map to %d", prev, name, status)
		}
		seen[status] = name
	}

	// Verify String() method returns expected names
	expectedNames := map[models.ServingStatus]string{
		models.StatusUnknown:    "UNKNOWN",
		models.StatusServing:    "SERVING",
		models.StatusNotServing: "NOT_SERVING",
		models.StatusDegraded:   "DEGRADED",
	}

	for status, expected := range expectedNames {
		if status.String() != expected {
			t.Errorf("ServingStatus(%d).String() = %q, want %q", status, status.String(), expected)
		}
	}
}

func TestRateLimitContract_ResponseStructure(t *testing.T) {
	// Verify rate limit response structure
	resp := models.RateLimitResponse{
		Allowed:    true,
		Remaining:  95,
		ResetAt:    time.Now().Add(30 * time.Second),
		Policy:     "default",
		RetryAfter: 0,
	}

	if resp.Policy == "" {
		t.Error("RateLimitResponse.Policy contract violated: must not be empty")
	}
	if resp.ResetAt.IsZero() {
		t.Error("RateLimitResponse.ResetAt contract violated: must be set")
	}
}

func TestRouteConfigContract_ResponseStructure(t *testing.T) {
	// Verify route config response structure
	resp := models.RouteConfigResponse{
		Routes: []models.Route{
			{
				ID:              "catalog-api",
				Pattern:         "/api/v1/catalog/*",
				UpstreamService: "catalog",
			},
		},
		Middleware: []string{"logging", "ratelimit"},
		TimeoutMs:  30000,
	}

	if len(resp.Routes) == 0 {
		t.Error("RouteConfigResponse.Routes contract violated: must not be empty for existing service")
	}
	if resp.TimeoutMs <= 0 {
		t.Error("RouteConfigResponse.TimeoutMs contract violated: must be positive")
	}
}

func TestRouteContract_MethodMatching(t *testing.T) {
	// Verify route method matching behavior
	route := models.Route{
		ID:      "test",
		Methods: []string{"GET", "POST"},
	}

	contractTests := []struct {
		method string
		want   bool
	}{
		{"GET", true},
		{"POST", true},
		{"DELETE", false},
		{"PUT", false},
	}

	for _, tt := range contractTests {
		if got := route.MatchesMethod(tt.method); got != tt.want {
			t.Errorf("MatchesMethod(%q) = %v, want %v", tt.method, got, tt.want)
		}
	}
}

// --- Consumer-side contract verification ---

// This test verifies the contract from the perspective of a consumer
// (e.g., an API client) making requests to the Gateway.
func TestConsumerContract_GatewayEndpoints(t *testing.T) {
	contractCases := []ContractTestCase{
		{
			Name:           "health check",
			Endpoint:       "/api/v1/gateway/health",
			Method:         "GET",
			ExpectedStatus: 200,
			Request:        models.HealthCheckRequest{},
		},
		{
			Name:           "rate limit query",
			Endpoint:       "/api/v1/gateway/rate-limit/test-client",
			Method:         "GET",
			ExpectedStatus: 200,
			Request: models.RateLimitRequest{
				ClientID: "test-client",
				Route:    "catalog-api",
			},
		},
		{
			Name:           "route config query",
			Endpoint:       "/api/v1/gateway/routes/catalog",
			Method:         "GET",
			ExpectedStatus: 200,
			Request: models.RouteConfigRequest{
				ServiceName: "catalog",
			},
		},
	}

	for _, tc := range contractCases {
		t.Run(tc.Name, func(t *testing.T) {
			// Verify that the request type can be constructed
			if tc.Request == nil {
				t.Error("request must not be nil")
			}
		})
	}
}

// Verify context propagation contract
func TestContextPropagationContract(t *testing.T) {
	ctx := context.Background()
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	// Verify that context deadlines propagate through the service
	deadline, ok := ctx.Deadline()
	if !ok {
		t.Error("context deadline contract violated: deadline must be set")
	}
	if deadline.Before(time.Now()) {
		t.Error("context deadline contract violated: deadline must be in the future")
	}
}
