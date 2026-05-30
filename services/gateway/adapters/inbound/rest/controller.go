// Package rest implements the inbound REST adapter for the Gateway service.
// It translates HTTP requests into domain-level use case calls and
// domain responses back into HTTP responses.
package rest

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/ports/inbound"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/services"
)

// Controller implements the REST API for the Gateway service.
// It maps HTTP endpoints to domain use case calls.
type Controller struct {
	routing     inbound.RoutingUseCase
	healthCheck inbound.HealthCheckUseCase
	rateLimit   inbound.RateLimitUseCase
	routeConfig inbound.RouteConfigUseCase
	logger      *slog.Logger
	mux         *http.ServeMux
}

// NewController creates a new REST controller with the given use case dependencies.
func NewController(
	routing inbound.RoutingUseCase,
	healthCheck inbound.HealthCheckUseCase,
	rateLimit inbound.RateLimitUseCase,
	routeConfig inbound.RouteConfigUseCase,
	logger *slog.Logger,
) *Controller {
	if logger == nil {
		logger = slog.Default()
	}

	c := &Controller{
		routing:     routing,
		healthCheck: healthCheck,
		rateLimit:   rateLimit,
		routeConfig: routeConfig,
		logger:      logger,
		mux:         http.NewServeMux(),
	}

	c.registerRoutes()
	return c
}

// Handler returns the HTTP handler for this controller.
func (c *Controller) Handler() http.Handler {
	return c.mux
}

// registerRoutes sets up the HTTP route patterns.
func (c *Controller) registerRoutes() {
	c.mux.HandleFunc("GET /api/v1/gateway/health", c.handleHealthCheck)
	c.mux.HandleFunc("GET /api/v1/gateway/rate-limit/{clientID}", c.handleGetRateLimit)
	c.mux.HandleFunc("GET /api/v1/gateway/routes/{service}", c.handleGetRouteConfig)
	// Catch-all proxy handler for routing requests
	c.mux.HandleFunc("/", c.handleRoute)
}

// handleHealthCheck handles GET /api/v1/gateway/health
func (c *Controller) handleHealthCheck(w http.ResponseWriter, r *http.Request) {
	c.logger.Debug("REST HealthCheck called",
		slog.String("remote_addr", r.RemoteAddr),
	)

	resp := c.healthCheck.HealthCheck(r.Context(), models.HealthCheckRequest{})

	type downstreamJSON struct {
		Service string `json:"service"`
		Status  string `json:"status"`
		Latency string `json:"latency,omitempty"`
		Error   string `json:"error,omitempty"`
	}

	type healthJSON struct {
		Status     string           `json:"status"`
		Uptime     string           `json:"uptime"`
		Downstream []downstreamJSON `json:"downstream"`
	}

	downstream := make([]downstreamJSON, 0, len(resp.Downstream))
	for _, d := range resp.Downstream {
		item := downstreamJSON{
			Service: d.Service,
			Status:  d.Status.String(),
		}
		if d.Latency > 0 {
			item.Latency = d.Latency.String()
		}
		if d.Error != "" {
			item.Error = d.Error
		}
		downstream = append(downstream, item)
	}

	body := healthJSON{
		Status:     resp.Status.String(),
		Uptime:     resp.Uptime.String(),
		Downstream: downstream,
	}

	c.writeJSON(w, http.StatusOK, body)
}

// handleGetRateLimit handles GET /api/v1/gateway/rate-limit/{clientID}
func (c *Controller) handleGetRateLimit(w http.ResponseWriter, r *http.Request) {
	clientID := r.PathValue("clientID")
	if clientID == "" {
		c.writeError(w, http.StatusBadRequest, "MISSING_CLIENT_ID", "clientID path parameter is required")
		return
	}

	route := r.URL.Query().Get("route")
	windowSecStr := r.URL.Query().Get("window")

	var window time.Duration
	if windowSecStr != "" {
		sec, err := strconv.ParseInt(windowSecStr, 10, 64)
		if err != nil {
			c.writeError(w, http.StatusBadRequest, "INVALID_WINDOW", "window must be a valid integer in seconds")
			return
		}
		window = time.Duration(sec) * time.Second
	}

	c.logger.Debug("REST GetRateLimit called",
		slog.String("client_id", clientID),
		slog.String("route", route),
	)

	resp, err := c.rateLimit.GetRateLimit(r.Context(), models.RateLimitRequest{
		ClientID: clientID,
		Route:    route,
		Window:   window,
	})
	if err != nil {
		c.logger.Error("rate limit query failed",
			slog.String("client_id", clientID),
			slog.String("error", err.Error()),
		)
		c.writeError(w, http.StatusInternalServerError, "RATE_LIMIT_ERROR", err.Error())
		return
	}

	type rateLimitJSON struct {
		Allowed    bool   `json:"allowed"`
		Remaining  int    `json:"remaining"`
		ResetAt    string `json:"reset_at"`
		Policy     string `json:"policy"`
		RetryAfter string `json:"retry_after,omitempty"`
	}

	body := rateLimitJSON{
		Allowed:   resp.Allowed,
		Remaining: resp.Remaining,
		ResetAt:   resp.ResetAt.Format(time.RFC3339),
		Policy:    resp.Policy,
	}
	if resp.RetryAfter > 0 {
		body.RetryAfter = resp.RetryAfter.String()
	}

	c.writeJSON(w, http.StatusOK, body)
}

// handleGetRouteConfig handles GET /api/v1/gateway/routes/{service}
func (c *Controller) handleGetRouteConfig(w http.ResponseWriter, r *http.Request) {
	service := r.PathValue("service")
	if service == "" {
		c.writeError(w, http.StatusBadRequest, "MISSING_SERVICE", "service path parameter is required")
		return
	}

	c.logger.Debug("REST GetRouteConfig called",
		slog.String("service", service),
	)

	resp, err := c.routeConfig.GetRouteConfig(r.Context(), models.RouteConfigRequest{
		ServiceName: service,
	})
	if err != nil {
		c.logger.Error("route config query failed",
			slog.String("service", service),
			slog.String("error", err.Error()),
		)
		c.writeError(w, http.StatusNotFound, "SERVICE_NOT_FOUND", err.Error())
		return
	}

	type routeJSON struct {
		ID              string            `json:"id"`
		Pattern         string            `json:"pattern"`
		Methods         []string          `json:"methods"`
		UpstreamService string            `json:"upstream_service"`
		UpstreamPath    string            `json:"upstream_path"`
		Timeout         string            `json:"timeout"`
		RetryCount      int               `json:"retry_count"`
		RateLimitPolicy string            `json:"rate_limit_policy"`
		RequireAuth     bool              `json:"require_auth"`
		Metadata        map[string]string `json:"metadata,omitempty"`
	}

	routes := make([]routeJSON, 0, len(resp.Routes))
	for _, r := range resp.Routes {
		routes = append(routes, routeJSON{
			ID:              r.ID,
			Pattern:         r.Pattern,
			Methods:         r.Methods,
			UpstreamService: r.UpstreamService,
			UpstreamPath:    r.UpstreamPath,
			Timeout:         r.Timeout.String(),
			RetryCount:      r.RetryCount,
			RateLimitPolicy: r.RateLimitPolicy,
			RequireAuth:     r.RequireAuth,
			Metadata:        r.Metadata,
		})
	}

	type routeConfigJSON struct {
		Routes     []routeJSON `json:"routes"`
		Middleware []string    `json:"middleware"`
		TimeoutMs  int         `json:"timeout_ms"`
	}

	c.writeJSON(w, http.StatusOK, routeConfigJSON{
		Routes:     routes,
		Middleware: resp.Middleware,
		TimeoutMs:  resp.TimeoutMs,
	})
}

// handleRoute handles the catch-all proxy endpoint for routing requests.
func (c *Controller) handleRoute(w http.ResponseWriter, r *http.Request) {
	c.logger.Debug("REST Route called",
		slog.String("method", r.Method),
		slog.String("path", r.URL.Path),
		slog.String("remote_addr", r.RemoteAddr),
	)

	// Extract headers
	headers := make(map[string]string)
	for k, v := range r.Header {
		if len(v) > 0 {
			headers[k] = v[0]
		}
	}

	// Read body (limited to 10MB for safety)
	var body []byte
	if r.Body != nil {
		r.Body = http.MaxBytesReader(w, r.Body, 10*1024*1024)
		body = make([]byte, 0)
		buf := make([]byte, 4096)
		for {
			n, err := r.Body.Read(buf)
			if n > 0 {
				body = append(body, buf[:n]...)
			}
			if err != nil {
				break
			}
		}
	}

	resp, err := c.routing.Route(r.Context(), models.RouteRequest{
		Method:  r.Method,
		Path:    r.URL.Path,
		Headers: headers,
		Body:    body,
	})
	if err != nil {
		c.handleRouteError(w, err)
		return
	}

	// Write response headers
	for k, v := range resp.Headers {
		w.Header().Set(k, v)
	}
	w.WriteHeader(int(resp.Status))
	if len(resp.Body) > 0 {
		_, _ = w.Write(resp.Body)
	}
}

// handleRouteError maps domain errors to HTTP status codes and writes responses.
func (c *Controller) handleRouteError(w http.ResponseWriter, err error) {
	switch e := err.(type) {
	case *services.RateLimitError:
		w.Header().Set("Retry-After", strconv.FormatInt(int64(e.RetryAfter.Seconds()), 10))
		w.Header().Set("X-RateLimit-Policy", e.Policy)
		c.writeError(w, http.StatusTooManyRequests, "RATE_LIMIT_EXCEEDED",
			fmt.Sprintf("rate limit exceeded, retry after %s", e.RetryAfter))
	case *services.UpstreamUnavailableError:
		c.writeError(w, http.StatusBadGateway, "UPSTREAM_UNAVAILABLE", e.Error())
	default:
		c.logger.Error("unhandled routing error",
			slog.String("error", err.Error()),
		)
		c.writeError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "an internal error occurred")
	}
}

// --- JSON response helpers ---

type errorResponse struct {
	Error   string `json:"error"`
	Code    string `json:"code"`
	Message string `json:"message"`
}

func (c *Controller) writeJSON(w http.ResponseWriter, statusCode int, body interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	if err := json.NewEncoder(w).Encode(body); err != nil {
		c.logger.Error("failed to encode JSON response",
			slog.String("error", err.Error()),
		)
	}
}

func (c *Controller) writeError(w http.ResponseWriter, statusCode int, code, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	resp := errorResponse{
		Error:   http.StatusText(statusCode),
		Code:    code,
		Message: message,
	}
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		c.logger.Error("failed to encode error response",
			slog.String("error", err.Error()),
		)
	}
}

// --- Middleware ---

// LoggingMiddleware returns an HTTP middleware that logs each request.
func LoggingMiddleware(logger *slog.Logger) func(http.Handler) http.Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now().UTC()
			next.ServeHTTP(w, r)
			logger.Info("HTTP request",
				slog.String("method", r.Method),
				slog.String("path", r.URL.Path),
				slog.Duration("duration", time.Since(start)),
				slog.String("remote_addr", r.RemoteAddr),
			)
		})
	}
}

// RecoveryMiddleware returns an HTTP middleware that recovers from panics.
func RecoveryMiddleware(logger *slog.Logger) func(http.Handler) http.Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if rec := recover(); rec != nil {
					logger.Error("panic recovered in HTTP handler",
						slog.Any("panic", rec),
						slog.String("method", r.Method),
						slog.String("path", r.URL.Path),
					)
					http.Error(w, `{"error":"Internal Server Error","code":"PANIC","message":"an unexpected error occurred"}`, http.StatusInternalServerError)
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}

// CORSMiddleware returns an HTTP middleware that adds CORS headers.
func CORSMiddleware(allowedOrigins []string) func(http.Handler) http.Handler {
	origins := "*"
	if len(allowedOrigins) > 0 {
		origins = allowedOrigins[0]
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Access-Control-Allow-Origin", origins)
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key, X-Client-ID, Traceparent")
			if r.Method == http.MethodOptions {
				w.WriteHeader(http.StatusNoContent)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}
