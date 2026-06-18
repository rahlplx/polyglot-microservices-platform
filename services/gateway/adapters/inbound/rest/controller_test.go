package rest

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
)

type mockRateLimitUseCase struct {
	err error
}

func (m *mockRateLimitUseCase) GetRateLimit(ctx context.Context, req models.RateLimitRequest) (models.RateLimitResponse, error) {
	return models.RateLimitResponse{}, m.err
}

type mockRouteConfigUseCase struct {
	err error
}

func (m *mockRouteConfigUseCase) GetRouteConfig(ctx context.Context, req models.RouteConfigRequest) (models.RouteConfigResponse, error) {
	return models.RouteConfigResponse{}, m.err
}

func TestController_InformationLeakage(t *testing.T) {
	internalErr := errors.New("sensitive database connection error: password=secret")

	ctrl := NewController(nil, nil, &mockRateLimitUseCase{err: internalErr}, &mockRouteConfigUseCase{err: internalErr}, nil)

	t.Run("handleGetRateLimit does not leak error", func(t *testing.T) {
		req := httptest.NewRequest("GET", "/api/v1/gateway/rate-limit/client1", nil)
		req.SetPathValue("clientID", "client1")
		w := httptest.NewRecorder()

		ctrl.handleGetRateLimit(w, req)

		if w.Code != http.StatusInternalServerError {
			t.Errorf("expected status 500, got %d", w.Code)
		}

		var resp errorResponse
		if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
			t.Fatalf("failed to decode response: %v", err)
		}

		if resp.Message == internalErr.Error() {
			t.Errorf("leaked sensitive error message: %q", resp.Message)
		}

		expected := "an internal error occurred while querying rate limit"
		if resp.Message != expected {
			t.Errorf("expected message %q, got %q", expected, resp.Message)
		}
	})

	t.Run("handleGetRouteConfig does not leak error", func(t *testing.T) {
		req := httptest.NewRequest("GET", "/api/v1/gateway/routes/service1", nil)
		req.SetPathValue("service", "service1")
		w := httptest.NewRecorder()

		ctrl.handleGetRouteConfig(w, req)

		if w.Code != http.StatusNotFound {
			t.Errorf("expected status 404, got %d", w.Code)
		}

		var resp errorResponse
		if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
			t.Fatalf("failed to decode response: %v", err)
		}

		if resp.Message == internalErr.Error() {
			t.Errorf("leaked sensitive error message: %q", resp.Message)
		}

		expected := "the requested service route configuration could not be found or retrieved"
		if resp.Message != expected {
			t.Errorf("expected message %q, got %q", expected, resp.Message)
		}
	})
}
