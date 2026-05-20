// Package services implements the core domain services for the Gateway.
// The RouterService orchestrates routing, health checking, rate limiting,
// and route configuration queries using outbound ports for infrastructure.
// ZERO external dependencies — only stdlib, domain models, and port interfaces.
package services

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/ports/outbound"
)

// RouterService implements all inbound use case interfaces:
//   - RoutingUseCase
//   - HealthCheckUseCase
//   - RateLimitUseCase
//   - RouteConfigUseCase
//
// It is the central domain service that coordinates routing decisions,
// health aggregation, and rate limit enforcement.
type RouterService struct {
	discovery outbound.ServiceDiscoveryPort
	limiter   outbound.RateLimiterPort

	mu       sync.RWMutex
	routes   map[string]models.Route           // route ID → Route
	policies map[string]models.RateLimitPolicy // policy name → Policy

	startedAt time.Time
	logger    *slog.Logger
}

// NewRouterService creates a new RouterService with the given outbound ports.
// The logger may be nil — a default discard logger is used in that case.
func NewRouterService(
	discovery outbound.ServiceDiscoveryPort,
	limiter outbound.RateLimiterPort,
	routes map[string]models.Route,
	policies map[string]models.RateLimitPolicy,
	logger *slog.Logger,
) *RouterService {
	if logger == nil {
		logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	}
	if routes == nil {
		routes = make(map[string]models.Route)
	}
	if policies == nil {
		policies = make(map[string]models.RateLimitPolicy)
	}
	return &RouterService{
		discovery: discovery,
		limiter:   limiter,
		routes:    routes,
		policies:  policies,
		startedAt: time.Now().UTC(),
		logger:    logger,
	}
}

// --- RoutingUseCase implementation ---

// Route resolves the target upstream for the given request, applies rate
// limiting, and returns a response from the upstream service.
func (s *RouterService) Route(ctx context.Context, req models.RouteRequest) (models.RouteResponse, error) {
	s.logger.Debug("routing request",
		slog.String("method", req.Method),
		slog.String("path", req.Path),
	)

	// Step 1: Match the route
	route, err := s.matchRoute(req.Method, req.Path)
	if err != nil {
		s.logger.Warn("route not found",
			slog.String("method", req.Method),
			slog.String("path", req.Path),
			slog.String("error", err.Error()),
		)
		return models.RouteResponse{}, fmt.Errorf("route not found for %s %s: %w", req.Method, req.Path, err)
	}

	// Step 2: Snapshot policies under read lock for consistent access
	s.mu.RLock()
	policiesSnapshot := make(map[string]models.RateLimitPolicy, len(s.policies))
	for k, v := range s.policies {
		policiesSnapshot[k] = v
	}
	s.mu.RUnlock()

	// Apply rate limiting if a policy is configured
	if route.RateLimitPolicy != "" {
		policy, ok := policiesSnapshot[route.RateLimitPolicy]
		if !ok {
			s.logger.Error("rate limit policy not found",
				slog.String("policy", route.RateLimitPolicy),
				slog.String("route_id", route.ID),
			)
			return models.RouteResponse{}, fmt.Errorf("rate limit policy %q not found for route %s: %w",
				route.RateLimitPolicy, route.ID, err)
		}

		key := s.buildRateLimitKey(req, route, policy)
		status, err := s.limiter.Allow(ctx, key, policy)
		if err != nil {
			s.logger.Error("rate limit check failed",
				slog.String("key", key),
				slog.String("error", err.Error()),
			)
			return models.RouteResponse{}, fmt.Errorf("rate limit check failed for key %q: %w", key, err)
		}

		if !status.Allowed {
			s.logger.Warn("rate limit exceeded",
				slog.String("key", key),
				slog.Int("remaining", status.Remaining),
				slog.String("reset_at", status.ResetAt.Format(time.RFC3339)),
			)
			return models.RouteResponse{}, &RateLimitError{
				Key:        key,
				Policy:     status.Policy,
				RetryAfter: status.RetryAfter,
				ResetAt:    status.ResetAt,
			}
		}
	}

	// Step 3: Resolve upstream endpoints
	endpoints, err := s.discovery.Resolve(ctx, route.UpstreamService)
	if err != nil {
		s.logger.Error("service discovery failed",
			slog.String("service", route.UpstreamService),
			slog.String("error", err.Error()),
		)
		return models.RouteResponse{}, fmt.Errorf("service discovery failed for %q: %w", route.UpstreamService, err)
	}

	if len(endpoints) == 0 {
		s.logger.Warn("no healthy upstream endpoints",
			slog.String("service", route.UpstreamService),
		)
		return models.RouteResponse{}, &UpstreamUnavailableError{
			Service: route.UpstreamService,
			Message: "no healthy endpoints available",
		}
	}

	// Step 4: Select an endpoint (simple round-robin via first healthy)
	endpoint := s.selectEndpoint(endpoints)

	// Step 5: Build the response. In a full implementation, this would
	// actually proxy the request to the upstream. For the domain service,
	// we return the routing decision with the selected endpoint metadata.
	upstreamPath := route.UpstreamPath
	if upstreamPath == "" {
		upstreamPath = req.Path
	}

	s.logger.Info("request routed",
		slog.String("route_id", route.ID),
		slog.String("upstream_service", route.UpstreamService),
		slog.String("upstream_address", endpoint.Address()),
		slog.String("upstream_path", upstreamPath),
	)

	return models.RouteResponse{
		Status:          200,
		Headers:         map[string]string{"X-Upstream-Service": route.UpstreamService, "X-Upstream-Address": endpoint.Address()},
		Body:            req.Body,
		UpstreamService: route.UpstreamService,
	}, nil
}

// --- HealthCheckUseCase implementation ---

// HealthCheck returns the current health status of the gateway and its
// downstream dependencies. This method never returns an error.
func (s *RouterService) HealthCheck(ctx context.Context, _ models.HealthCheckRequest) models.HealthCheckResponse {
	services, err := s.discovery.ListServices(ctx)
	if err != nil {
		s.logger.Error("failed to list services for health check",
			slog.String("error", err.Error()),
		)
		return models.HealthCheckResponse{
			Status: models.StatusDegraded,
			Uptime: time.Since(s.startedAt),
			Downstream: []models.DownstreamHealth{
				{
					Service: "discovery",
					Status:  models.StatusNotServing,
					Error:   fmt.Sprintf("service discovery unavailable: %v", err),
				},
			},
		}
	}

	overallStatus := models.StatusServing
	downstream := make([]models.DownstreamHealth, 0, len(services))

	for _, svc := range services {
		endpoints, err := s.discovery.Resolve(ctx, svc)
		if err != nil {
			s.logger.Warn("health check: could not resolve service",
				slog.String("service", svc),
				slog.String("error", err.Error()),
			)
			downstream = append(downstream, models.DownstreamHealth{
				Service: svc,
				Status:  models.StatusUnknown,
				Error:   fmt.Sprintf("resolve failed: %v", err),
			})
			overallStatus = models.StatusDegraded
			continue
		}

		healthy := 0
		for _, ep := range endpoints {
			if ep.Healthy {
				healthy++
			}
		}

		if healthy == 0 {
			downstream = append(downstream, models.DownstreamHealth{
				Service: svc,
				Status:  models.StatusNotServing,
				Error:   "no healthy endpoints",
			})
			overallStatus = models.StatusDegraded
		} else if healthy < len(endpoints) {
			downstream = append(downstream, models.DownstreamHealth{
				Service: svc,
				Status:  models.StatusDegraded,
			})
			// Don't degrade overall for partial endpoint loss
		} else {
			downstream = append(downstream, models.DownstreamHealth{
				Service: svc,
				Status:  models.StatusServing,
			})
		}
	}

	return models.HealthCheckResponse{
		Status:     overallStatus,
		Uptime:     time.Since(s.startedAt),
		Downstream: downstream,
	}
}

// --- RateLimitUseCase implementation ---

// GetRateLimit returns the current rate limit status for the given client
// and route combination without consuming a token.
func (s *RouterService) GetRateLimit(ctx context.Context, req models.RateLimitRequest) (models.RateLimitResponse, error) {
	// Find the route to determine which policy applies
	var policy models.RateLimitPolicy
	found := false

	s.mu.RLock()
	for _, route := range s.routes {
		if s.pathMatchesRoute(req.Route, route.Pattern) {
			if route.RateLimitPolicy != "" {
				if p, ok := s.policies[route.RateLimitPolicy]; ok {
					policy = p
					found = true
					break
				}
			}
		}
	}
	s.mu.RUnlock()

	if !found {
		// Use a default permissive policy
		policy = models.RateLimitPolicy{
			Name:           "default",
			RequestsPerSec: 1000,
			BurstSize:      2000,
			Window:         60 * time.Second,
			KeyTemplate:    "{{.ClientID}}:{{.Route}}",
		}
	}

	key := s.buildRateLimitKeyFromReq(req, policy)
	status, err := s.limiter.GetStatus(ctx, key, policy)
	if err != nil {
		return models.RateLimitResponse{}, fmt.Errorf("failed to get rate limit status for key %q: %w", key, err)
	}

	return models.RateLimitResponse{
		Allowed:    status.Allowed,
		Remaining:  status.Remaining,
		ResetAt:    status.ResetAt,
		Policy:     status.Policy,
		RetryAfter: status.RetryAfter,
	}, nil
}

// --- RouteConfigUseCase implementation ---

// GetRouteConfig returns the routing configuration for the requested service.
func (s *RouterService) GetRouteConfig(ctx context.Context, req models.RouteConfigRequest) (models.RouteConfigResponse, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var matched []models.Route
	middlewareSet := make(map[string]struct{})
	defaultTimeoutMs := 30000 // 30s default

	for _, route := range s.routes {
		if req.ServiceName != "" && route.UpstreamService != req.ServiceName {
			continue
		}
		matched = append(matched, route)
		for _, mw := range route.Middleware {
			middlewareSet[mw] = struct{}{}
		}
		if route.Timeout > 0 {
			timeoutMs := int(route.Timeout.Milliseconds())
			if timeoutMs > defaultTimeoutMs {
				defaultTimeoutMs = timeoutMs
			}
		}
	}

	if req.ServiceName != "" && len(matched) == 0 {
		return models.RouteConfigResponse{}, fmt.Errorf("service %q not found in route table", req.ServiceName)
	}

	middleware := make([]string, 0, len(middlewareSet))
	for mw := range middlewareSet {
		middleware = append(middleware, mw)
	}

	return models.RouteConfigResponse{
		Routes:     matched,
		Middleware: middleware,
		TimeoutMs:  defaultTimeoutMs,
	}, nil
}

// --- Helper methods ---

// matchRoute finds the first route that matches the given method and path.
func (s *RouterService) matchRoute(method, path string) (models.Route, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	for _, route := range s.routes {
		if !route.MatchesMethod(method) {
			continue
		}
		if s.pathMatchesRoute(path, route.Pattern) {
			return route, nil
		}
	}
	return models.Route{}, fmt.Errorf("no route matches %s %s", method, path)
}

// pathMatchesRoute performs simple pattern matching.
// Supports exact matches and wildcard suffix patterns (e.g., "/api/v1/catalog/*").
func (s *RouterService) pathMatchesRoute(path, pattern string) bool {
	if pattern == path {
		return true
	}
	if strings.HasSuffix(pattern, "/*") {
		prefix := strings.TrimSuffix(pattern, "/*")
		return strings.HasPrefix(path, prefix+"/") || path == prefix
	}
	if strings.HasSuffix(pattern, "/") {
		return strings.HasPrefix(path, pattern)
	}
	return false
}

// selectEndpoint picks the first healthy endpoint from the list.
// In a production system, this would implement round-robin, weighted,
// or least-connection load balancing.
func (s *RouterService) selectEndpoint(endpoints []models.ServiceEndpoint) models.ServiceEndpoint {
	for _, ep := range endpoints {
		if ep.Healthy {
			return ep
		}
	}
	// Fallback: return first endpoint even if unhealthy
	return endpoints[0]
}

// buildRateLimitKey constructs the rate limit key from a RouteRequest and route.
func (s *RouterService) buildRateLimitKey(req models.RouteRequest, route models.Route, policy models.RateLimitPolicy) string {
	// Extract client ID from headers or use a default
	clientID := req.Headers["X-API-Key"]
	if clientID == "" {
		clientID = req.Headers["X-Client-ID"]
	}
	if clientID == "" {
		clientID = "anonymous"
	}
	// Simple template substitution
	key := strings.ReplaceAll(policy.KeyTemplate, "{{.ClientID}}", clientID)
	key = strings.ReplaceAll(key, "{{.Route}}", route.ID)
	return key
}

// buildRateLimitKeyFromReq constructs the rate limit key from a RateLimitRequest.
func (s *RouterService) buildRateLimitKeyFromReq(req models.RateLimitRequest, policy models.RateLimitPolicy) string {
	key := strings.ReplaceAll(policy.KeyTemplate, "{{.ClientID}}", req.ClientID)
	key = strings.ReplaceAll(key, "{{.Route}}", req.Route)
	return key
}

// SetRoutes replaces the current route table. Used for hot-reloading
// configuration changes without restarting the service.
func (s *RouterService) SetRoutes(routes map[string]models.Route) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.routes = routes
	s.logger.Info("route table updated", slog.Int("route_count", len(routes)))
}

// SetPolicies replaces the current rate limit policies.
func (s *RouterService) SetPolicies(policies map[string]models.RateLimitPolicy) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.policies = policies
	s.logger.Info("rate limit policies updated", slog.Int("policy_count", len(policies)))
}

// --- Domain Errors ---

// RateLimitError is returned when a request exceeds the rate limit.
type RateLimitError struct {
	Key        string
	Policy     string
	RetryAfter time.Duration
	ResetAt    time.Time
}

func (e *RateLimitError) Error() string {
	return fmt.Sprintf("rate limit exceeded for key %q under policy %q (retry after %s)",
		e.Key, e.Policy, e.RetryAfter)
}

// UpstreamUnavailableError is returned when no healthy upstream endpoints exist.
type UpstreamUnavailableError struct {
	Service string
	Message string
}

func (e *UpstreamUnavailableError) Error() string {
	return fmt.Sprintf("upstream service %q unavailable: %s", e.Service, e.Message)
}
