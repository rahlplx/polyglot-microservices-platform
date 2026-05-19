// Package outbound defines the driven port interfaces for the Gateway domain.
// This file provides the RateLimiterPort interface.
package outbound

import (
	"context"

	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
)

// RateLimiterPort defines the interface for rate limiting operations.
// Implementations must support token bucket semantics with configurable
// refill rates and burst sizes per policy.
type RateLimiterPort interface {
	// Allow checks whether a request with the given key is allowed under
	// the specified rate limit policy. It atomically consumes one token
	// if allowed. Returns the current status regardless of the allow decision.
	Allow(ctx context.Context, key string, policy models.RateLimitPolicy) (models.RateLimitStatus, error)

	// GetStatus returns the current rate limit status for the given key
	// without consuming a token. Useful for observability and admin queries.
	GetStatus(ctx context.Context, key string, policy models.RateLimitPolicy) (models.RateLimitStatus, error)

	// Reset clears the rate limit counter for the given key.
	// Typically used for admin operations or testing.
	Reset(ctx context.Context, key string) error
}
