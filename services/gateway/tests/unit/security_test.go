package services_test

import (
	"bytes"
	"context"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/services"
)

func TestRouterService_LogSecurity(t *testing.T) {
	var buf bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&buf, nil))

	routes := map[string]models.Route{
		"secure-api": {
			ID:              "secure-api",
			Pattern:         "/api/v1/secure/*",
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

	secretKey := "sk_live_1234567890abcdef"
	limiter := &mockRateLimiter{
		status: models.RateLimitStatus{
			Allowed:    false,
			Remaining:  0,
			Policy:     "strict",
			RetryAfter: 5 * time.Second,
			ResetAt:    time.Now().Add(5 * time.Second),
		},
	}

	svc := services.NewRouterService(discovery, limiter, routes, policies, logger)

	_, err := svc.Route(context.Background(), models.RouteRequest{
		Method:  "GET",
		Path:    "/api/v1/secure/resource",
		Headers: map[string]string{"X-API-Key": secretKey},
	})

	if err == nil {
		t.Fatal("expected rate limit error, got nil")
	}

	logOutput := buf.String()
	// The key in buildRateLimitKey is constructed as "{{.ClientID}}:{{.Route}}"
	// which will be "sk_live_1234567890abcdef:secure-api"
	secretKeyPart := secretKey

	if strings.Contains(logOutput, secretKeyPart) {
		t.Errorf("found sensitive secret key part %q in logs, it should have been masked.\nLogs: %s", secretKeyPart, logOutput)
	}

	// Also check RateLimitError.Error()
	if strings.Contains(err.Error(), secretKeyPart) {
		t.Errorf("found sensitive secret key part %q in error message, it should have been masked.\nError: %v", secretKeyPart, err)
	}

	// Verify masking is present (shows first 4 and last 4)
	// sk_l****-api
	if !strings.Contains(logOutput, "sk_l****") {
		t.Errorf("expected masked key to be in logs, but it was not found.\nLogs: %s", logOutput)
	}
}
