// Package outbound defines the driven port interfaces (infrastructure interfaces)
// for the Payment domain. This file provides the CircuitBreakerPort interface
// for circuit breaker operations. The circuit breaker state types are defined
// in the domain models package (models.CircuitState, models.CircuitBreakerConfig,
// models.CircuitBreakerState) to maintain the hexagonal architecture principle
// that domain types belong in the domain layer, not in the ports layer. The
// port interface depends on the domain model types, not the other way around.
package outbound

import (
	"context"

	"github.com/gstack/payment-service/domain/models"
)

// CircuitBreakerPort defines the interface for circuit breaker operations.
// The circuit breaker wraps all calls to the external payment gateway,
// providing automatic fail-fast behavior when the gateway is unavailable.
// This port abstracts the circuit breaker implementation (sony/gobreaker
// in the resilience adapter) from the domain services, ensuring that the
// domain layer has no dependency on the specific circuit breaker library.
// The port follows the Execute-around pattern, where the caller provides
// a function and the circuit breaker decides whether to execute it based
// on the current state.
type CircuitBreakerPort interface {
	// Execute wraps a function call with circuit breaker protection.
	// If the circuit is Open, it immediately returns a GatewayUnavailableError
	// without calling the function. If the circuit is Closed or HalfOpen,
	// it calls the function and records the result (success or failure)
	// to update the circuit breaker state. Returns the function's result
	// or an error from either the function or the circuit breaker.
	Execute(ctx context.Context, fn func(ctx context.Context) error) error

	// GetState returns the current state of the circuit breaker for
	// monitoring and operational visibility. The returned snapshot is
	// immutable and provides a consistent view at the time of the call.
	GetState(ctx context.Context) models.CircuitBreakerState

	// Reset forcefully resets the circuit breaker to Closed state.
	// This is an administrative operation that should be used with
	// caution, as it bypasses the normal state machine transitions.
	// It is typically used during operational incidents when an operator
	// has verified that the external gateway has recovered.
	Reset(ctx context.Context) error
}
