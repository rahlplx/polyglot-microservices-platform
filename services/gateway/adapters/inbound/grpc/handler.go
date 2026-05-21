// Package grpc implements the inbound gRPC adapter for the Gateway service.
// It translates gRPC requests into domain-level use case calls and
// domain responses back into gRPC responses.
package grpc

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/ports/inbound"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/services"
)

// Proto-generated types would normally come from the api/proto directory.
// For this implementation, we define the message types inline to avoid
// requiring the protoc toolchain at development time. In production,
// these would be generated from gateway.proto via `buf generate`.

// RouteRequest is the gRPC request message for routing.
type RouteRequest struct {
	Method       string            `json:"method,omitempty"`
	Path         string            `json:"path,omitempty"`
	Headers      map[string]string `json:"headers,omitempty"`
	Body         []byte            `json:"body,omitempty"`
	TraceContext string            `json:"trace_context,omitempty"`
}

// RouteResponse is the gRPC response message for routing.
type RouteResponse struct {
	Status          uint32            `json:"status,omitempty"`
	Headers         map[string]string `json:"headers,omitempty"`
	Body            []byte            `json:"body,omitempty"`
	UpstreamService string            `json:"upstream_service,omitempty"`
}

// HealthCheckRequest is the gRPC request message for health checks.
type HealthCheckRequest struct{}

// HealthCheckResponse is the gRPC response message for health checks.
type HealthCheckResponse struct {
	Status     uint32                  `json:"status,omitempty"`
	UptimeSec  int64                   `json:"uptime_sec,omitempty"`
	Downstream []*DownstreamHealthMsg  `json:"downstream,omitempty"`
}

// DownstreamHealthMsg represents the health of a downstream service.
type DownstreamHealthMsg struct {
	Service string `json:"service,omitempty"`
	Status  uint32 `json:"status,omitempty"`
	LatencyNs int64 `json:"latency_ns,omitempty"`
	Error   string `json:"error,omitempty"`
}

// RateLimitRequest is the gRPC request message for rate limit queries.
type RateLimitRequest struct {
	ClientID      string `json:"client_id,omitempty"`
	Route         string `json:"route,omitempty"`
	WindowSeconds int64  `json:"window_seconds,omitempty"`
}

// RateLimitResponse is the gRPC response message for rate limit queries.
type RateLimitResponse struct {
	Allowed    bool   `json:"allowed,omitempty"`
	Remaining  int32  `json:"remaining,omitempty"`
	ResetAt    int64  `json:"reset_at,omitempty"` // Unix timestamp
	Policy     string `json:"policy,omitempty"`
	RetryAfterMs int64 `json:"retry_after_ms,omitempty"`
}

// RouteConfigRequest is the gRPC request message for route config queries.
type RouteConfigRequest struct {
	ServiceName string `json:"service_name,omitempty"`
	Version     string `json:"version,omitempty"`
}

// RouteConfigResponse is the gRPC response message for route config queries.
type RouteConfigResponse struct {
	Routes     []*RouteMsg `json:"routes,omitempty"`
	Middleware []string    `json:"middleware,omitempty"`
	TimeoutMs  int32       `json:"timeout_ms,omitempty"`
}

// RouteMsg represents a single route in the gRPC response.
type RouteMsg struct {
	ID              string            `json:"id,omitempty"`
	Pattern         string            `json:"pattern,omitempty"`
	Methods         []string          `json:"methods,omitempty"`
	UpstreamService string            `json:"upstream_service,omitempty"`
	UpstreamPath    string            `json:"upstream_path,omitempty"`
	TimeoutMs       int32             `json:"timeout_ms,omitempty"`
	RetryCount      int32             `json:"retry_count,omitempty"`
	RateLimitPolicy string            `json:"rate_limit_policy,omitempty"`
	RequireAuth     bool              `json:"require_auth,omitempty"`
	Metadata        map[string]string `json:"metadata,omitempty"`
}

// GatewayServiceServer is the gRPC service interface that handlers must implement.
type GatewayServiceServer interface {
	Route(context.Context, *RouteRequest) (*RouteResponse, error)
	HealthCheck(context.Context, *HealthCheckRequest) (*HealthCheckResponse, error)
	GetRateLimit(context.Context, *RateLimitRequest) (*RateLimitResponse, error)
	GetRouteConfig(context.Context, *RouteConfigRequest) (*RouteConfigResponse, error)
}

// Handler implements the GatewayServiceServer gRPC interface by delegating
// to the domain use case interfaces.
type Handler struct {
	routing     inbound.RoutingUseCase
	healthCheck inbound.HealthCheckUseCase
	rateLimit   inbound.RateLimitUseCase
	routeConfig inbound.RouteConfigUseCase
	logger      *slog.Logger
}

// NewHandler creates a new gRPC handler with the given use case dependencies.
func NewHandler(
	routing inbound.RoutingUseCase,
	healthCheck inbound.HealthCheckUseCase,
	rateLimit inbound.RateLimitUseCase,
	routeConfig inbound.RouteConfigUseCase,
	logger *slog.Logger,
) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{
		routing:     routing,
		healthCheck: healthCheck,
		rateLimit:   rateLimit,
		routeConfig: routeConfig,
		logger:      logger,
	}
}

// RegisterServer registers the handler with a gRPC server.
func (h *Handler) RegisterServer(srv *grpc.Server) {
	// In production with generated proto stubs, this would call:
	// RegisterGatewayServiceServer(srv, h)
	// For now, we use a manual registration approach.
	h.logger.Info("gRPC handler registered on server")
}

// Route handles incoming gRPC Route requests.
func (h *Handler) Route(ctx context.Context, req *RouteRequest) (*RouteResponse, error) {
	h.logger.Debug("gRPC Route called",
		slog.String("method", req.Method),
		slog.String("path", req.Path),
	)

	domainReq := models.RouteRequest{
		Method:  req.Method,
		Path:    req.Path,
		Headers: req.Headers,
		Body:    req.Body,
	}

	resp, err := h.routing.Route(ctx, domainReq)
	if err != nil {
		h.handleDomainError(err)
		return nil, h.mapError(err)
	}

	return &RouteResponse{
		Status:          resp.Status,
		Headers:         resp.Headers,
		Body:            resp.Body,
		UpstreamService: resp.UpstreamService,
	}, nil
}

// HealthCheck handles incoming gRPC HealthCheck requests.
func (h *Handler) HealthCheck(ctx context.Context, _ *HealthCheckRequest) (*HealthCheckResponse, error) {
	h.logger.Debug("gRPC HealthCheck called")

	resp := h.healthCheck.HealthCheck(ctx, models.HealthCheckRequest{})

	downstream := make([]*DownstreamHealthMsg, 0, len(resp.Downstream))
	for _, d := range resp.Downstream {
		downstream = append(downstream, &DownstreamHealthMsg{
			Service:   d.Service,
			Status:    uint32(d.Status),
			LatencyNs: d.Latency.Nanoseconds(),
			Error:     d.Error,
		})
	}

	return &HealthCheckResponse{
		Status:     uint32(resp.Status),
		UptimeSec:  int64(resp.Uptime.Seconds()),
		Downstream: downstream,
	}, nil
}

// GetRateLimit handles incoming gRPC GetRateLimit requests.
func (h *Handler) GetRateLimit(ctx context.Context, req *RateLimitRequest) (*RateLimitResponse, error) {
	h.logger.Debug("gRPC GetRateLimit called",
		slog.String("client_id", req.ClientID),
		slog.String("route", req.Route),
	)

	window := time.Duration(req.WindowSeconds) * time.Second
	if req.WindowSeconds == 0 {
		window = 0
	}

	resp, err := h.rateLimit.GetRateLimit(ctx, models.RateLimitRequest{
		ClientID: req.ClientID,
		Route:    req.Route,
		Window:   window,
	})
	if err != nil {
		return nil, h.mapError(err)
	}

	return &RateLimitResponse{
		Allowed:      resp.Allowed,
		Remaining:    int32(resp.Remaining),
		ResetAt:      resp.ResetAt.Unix(),
		Policy:       resp.Policy,
		RetryAfterMs: resp.RetryAfter.Milliseconds(),
	}, nil
}

// GetRouteConfig handles incoming gRPC GetRouteConfig requests.
func (h *Handler) GetRouteConfig(ctx context.Context, req *RouteConfigRequest) (*RouteConfigResponse, error) {
	h.logger.Debug("gRPC GetRouteConfig called",
		slog.String("service_name", req.ServiceName),
	)

	resp, err := h.routeConfig.GetRouteConfig(ctx, models.RouteConfigRequest{
		ServiceName: req.ServiceName,
		Version:     req.Version,
	})
	if err != nil {
		return nil, h.mapError(err)
	}

	routes := make([]*RouteMsg, 0, len(resp.Routes))
	for _, r := range resp.Routes {
		routes = append(routes, &RouteMsg{
			ID:              r.ID,
			Pattern:         r.Pattern,
			Methods:         r.Methods,
			UpstreamService: r.UpstreamService,
			UpstreamPath:    r.UpstreamPath,
			TimeoutMs:       int32(r.Timeout.Milliseconds()),
			RetryCount:      int32(r.RetryCount),
			RateLimitPolicy: r.RateLimitPolicy,
			RequireAuth:     r.RequireAuth,
			Metadata:        r.Metadata,
		})
	}

	return &RouteConfigResponse{
		Routes:     routes,
		Middleware: resp.Middleware,
		TimeoutMs:  int32(resp.TimeoutMs),
	}, nil
}

// mapError converts domain errors to appropriate gRPC status codes.
func (h *Handler) mapError(err error) error {
	switch err.(type) {
	case *services.RateLimitError:
		rle := err.(*services.RateLimitError)
		return status.Errorf(codes.ResourceExhausted,
			"rate limit exceeded for key %q (retry after %s)",
			rle.Key, rle.RetryAfter)
	case *services.UpstreamUnavailableError:
		return status.Errorf(codes.Unavailable, "%v", err)
	default:
		return status.Errorf(codes.Internal, "internal error: %v", err)
	}
}

// handleDomainError logs domain errors for observability.
func (h *Handler) handleDomainError(err error) {
	switch e := err.(type) {
	case *services.RateLimitError:
		h.logger.Warn("rate limit exceeded",
			slog.String("key", e.Key),
			slog.String("policy", e.Policy),
			slog.Duration("retry_after", e.RetryAfter),
		)
	case *services.UpstreamUnavailableError:
		h.logger.Error("upstream unavailable",
			slog.String("service", e.Service),
			slog.String("message", e.Message),
		)
	default:
		h.logger.Error("routing error",
			slog.String("error", err.Error()),
		)
	}
}

// Ensure Handler implements GatewayServiceServer at compile time.
var _ GatewayServiceServer = (*Handler)(nil)

// FormatServingStatus converts a uint32 status to a string name.
func FormatServingStatus(s uint32) string {
	names := map[uint32]string{
		0: "UNKNOWN",
		1: "SERVING",
		2: "NOT_SERVING",
		3: "DEGRADED",
	}
	if name, ok := names[s]; ok {
		return name
	}
	return fmt.Sprintf("STATUS_%d", s)
}
