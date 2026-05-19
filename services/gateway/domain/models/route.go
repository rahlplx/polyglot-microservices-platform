// Package models defines the core domain models for the Gateway service.
// These types have ZERO external dependencies — only stdlib and domain types.
package models

import (
	"fmt"
	"time"
)

// ServingStatus represents the health status of a service or the gateway itself.
type ServingStatus int

const (
	StatusUnknown   ServingStatus = iota // Status is unknown
	StatusServing                        // Service is healthy and serving requests
	StatusNotServing                     // Service is unavailable
	StatusDegraded                       // Service is partially available
)

// String returns a human-readable representation of the ServingStatus.
func (s ServingStatus) String() string {
	names := [...]string{"UNKNOWN", "SERVING", "NOT_SERVING", "DEGRADED"}
	if s < 0 || int(s) >= len(names) {
		return "UNKNOWN"
	}
	return names[s]
}

// ServiceEndpoint represents a single upstream service instance discovered
// through service discovery. It contains the network address and metadata
// needed to route requests to this endpoint.
type ServiceEndpoint struct {
	Name      string            // Service name (e.g., "catalog", "order")
	Host      string            // Hostname or IP address
	Port      int               // Port number
	Protocol  string            // Protocol: "grpc" or "http"
	Metadata  map[string]string // Arbitrary metadata (version, weight, zone)
	Healthy   bool              // Whether the endpoint passed the last health check
	UpdatedAt time.Time         // Last time this endpoint was updated
}

// Address returns the host:port combination for this endpoint.
func (e ServiceEndpoint) Address() string {
	return fmt.Sprintf("%s:%d", e.Host, e.Port)
}

// IsGRPC returns true if the endpoint speaks gRPC.
func (e ServiceEndpoint) IsGRPC() bool {
	return e.Protocol == "grpc"
}

// Route represents a routing rule that maps incoming request patterns to
// upstream services. Routes are loaded from configuration and may be
// updated dynamically through service discovery or config changes.
type Route struct {
	ID              string            // Unique route identifier
	Pattern         string            // Path pattern (e.g., "/api/v1/catalog/*")
	Methods         []string          // Allowed HTTP methods (empty = all)
	UpstreamService string            // Target service name
	UpstreamPath    string            // Rewritten upstream path (empty = passthrough)
	Timeout         time.Duration     // Request timeout
	RetryCount      int               // Number of retries on upstream failure
	RateLimitPolicy string            // Rate limit policy name to apply
	RequireAuth     bool              // Whether authentication is required
	Middleware      []string          // Ordered list of middleware names to apply
	Metadata        map[string]string // Arbitrary route metadata
	CreatedAt       time.Time         // Route creation timestamp
	UpdatedAt       time.Time         // Route last update timestamp
}

// MatchesMethod returns true if the route allows the given HTTP method.
// An empty Methods list means all methods are allowed.
func (r Route) MatchesMethod(method string) bool {
	if len(r.Methods) == 0 {
		return true
	}
	for _, m := range r.Methods {
		if m == method || m == "*" {
			return true
		}
	}
	return false
}

// RateLimitPolicy defines the token bucket parameters for rate limiting
// a specific client/route combination.
type RateLimitPolicy struct {
	Name          string        // Policy identifier
	RequestsPerSec float64      // Token refill rate (tokens per second)
	BurstSize     int           // Maximum tokens in the bucket (burst capacity)
	Window        time.Duration // Sliding window duration for counting
	KeyTemplate   string        // Go template for the rate limit key (e.g., "{{.ClientID}}:{{.Route}}")
}

// RateLimitStatus represents the current state of a rate limit counter
// for a given client and route.
type RateLimitStatus struct {
	Key       string        // The resolved rate limit key
	Allowed   bool          // Whether the request is allowed
	Remaining int           // Remaining tokens in the current window
	Limit     int           // Maximum tokens in the window
	ResetAt   time.Time     // When the window resets
	Policy    string        // Name of the applied policy
	RetryAfter time.Duration // Duration until the client should retry (0 if allowed)
}

// RouteRequest is the domain-level input for the routing use case.
type RouteRequest struct {
	Method  string            // HTTP method (GET, POST, etc.)
	Path    string            // Request path
	Headers map[string]string // Request headers
	Body    []byte            // Request body (binary-safe)
}

// RouteResponse is the domain-level output of the routing use case.
type RouteResponse struct {
	Status          uint32            // HTTP status code
	Headers         map[string]string // Response headers
	Body            []byte            // Response body
	UpstreamService string            // Name of upstream service that handled the request
}

// HealthCheckRequest is the domain-level input for the health check use case.
type HealthCheckRequest struct{}

// DownstreamHealth represents the health status of a downstream dependency.
type DownstreamHealth struct {
	Service string        // Service name
	Status  ServingStatus // Health status
	Latency time.Duration // Last measured latency (0 if unknown)
	Error   string        // Last error message (empty if healthy)
}

// HealthCheckResponse is the domain-level output of the health check use case.
type HealthCheckResponse struct {
	Status     ServingStatus       // Overall gateway health
	Uptime     time.Duration       // Gateway uptime
	Downstream []DownstreamHealth  // Health of each downstream service
}

// RateLimitRequest is the domain-level input for querying rate limit status.
type RateLimitRequest struct {
	ClientID string // Client identifier (from X-API-Key or mTLS SVID)
	Route    string // Route pattern being accessed
	Window   time.Duration // Requested window (0 = use policy default)
}

// RateLimitResponse is the domain-level output for rate limit queries.
type RateLimitResponse struct {
	Allowed   bool           // Whether the request is allowed
	Remaining int            // Remaining requests in the window
	ResetAt   time.Time      // When the window resets
	Policy    string         // Applied policy name
	RetryAfter time.Duration // Duration to wait before retrying
}

// RouteConfigRequest is the domain-level input for querying route configuration.
type RouteConfigRequest struct {
	ServiceName string // Service to query (empty = all services)
	Version     string // Version filter (empty = all versions)
}

// RouteConfigResponse is the domain-level output for route configuration queries.
type RouteConfigResponse struct {
	Routes     []Route          // Matching routes
	Middleware []string         // Active middleware names
	TimeoutMs  int              // Default timeout in milliseconds
}
