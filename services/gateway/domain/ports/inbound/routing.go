// Package inbound defines the driving port interfaces (use cases) for the Gateway domain.
// These interfaces represent the capabilities that the Gateway exposes to the outside world.
// ZERO external dependencies — only stdlib and domain types.
package inbound

import (
	"context"

	"github.com/comprehensive-architecture/services/gateway/domain/models"
)

// RoutingUseCase defines the core routing capability of the Gateway.
// Implementations accept incoming requests, resolve the target upstream
// service, apply rate limiting, and forward the request.
type RoutingUseCase interface {
	// Route resolves the target upstream for the given request and proxies it.
	// Returns a RouteResponse with the upstream's reply or an error if routing
	// fails (route not found, rate limit exceeded, upstream unavailable).
	Route(ctx context.Context, req models.RouteRequest) (models.RouteResponse, error)
}

// HealthCheckUseCase defines the health checking capability of the Gateway.
// Implementations aggregate the gateway's own health with downstream service health.
type HealthCheckUseCase interface {
	// HealthCheck returns the current health status of the gateway and its
	// downstream dependencies. This method must never return an error — even
	// in a degraded state, it returns a response with appropriate status.
	HealthCheck(ctx context.Context, req models.HealthCheckRequest) models.HealthCheckResponse
}

// RateLimitUseCase defines the rate limit querying capability of the Gateway.
// Implementations check the current rate limit status for a client/route pair.
type RateLimitUseCase interface {
	// GetRateLimit returns the current rate limit status for the given client
	// and route. Returns an error only for invalid input (unknown client or policy).
	GetRateLimit(ctx context.Context, req models.RateLimitRequest) (models.RateLimitResponse, error)
}

// RouteConfigUseCase defines the route configuration querying capability.
// Implementations return the current routing table for a service or all services.
type RouteConfigUseCase interface {
	// GetRouteConfig returns the routing configuration for the requested service.
	// If ServiceName is empty, returns all routes. Returns an error if the
	// specified service is not found.
	GetRouteConfig(ctx context.Context, req models.RouteConfigRequest) (models.RouteConfigResponse, error)
}
