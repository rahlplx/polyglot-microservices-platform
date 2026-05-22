// Package resilience implements the outbound circuit breaker adapter for
// the Payment service. It uses the sony/gobreaker library to implement
// the CircuitBreakerPort interface, providing Resilience4j-style circuit
// breaker semantics with three states: Closed, Open, and HalfOpen. The
// circuit breaker wraps all calls to the external payment gateway,
// providing automatic fail-fast behavior when the gateway is unavailable.
package resilience

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/sony/gobreaker"

	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/ports/outbound"
)

// CircuitBreakerAdapter implements the CircuitBreakerPort interface using
// the sony/gobreaker library. It wraps the gobreaker.CircuitBreaker with
// the domain-oriented CircuitBreakerPort interface, providing a clean
// boundary between the infrastructure library and the domain services.
type CircuitBreakerAdapter struct {
	cb     *gobreaker.CircuitBreaker
	logger *slog.Logger
}

// NewCircuitBreakerAdapter creates a new circuit breaker adapter with the
// given configuration. It initializes the gobreaker instance with production
// defaults: 5 consecutive failures trigger Open, 30s timeout before HalfOpen,
// and 1 probe request allowed in HalfOpen.
func NewCircuitBreakerAdapter(config models.CircuitConfig, logger *slog.Logger) *CircuitBreakerAdapter {
	if logger == nil {
		logger = slog.Default()
	}

	cbSettings := gobreaker.Settings{
		Name:        config.Name,
		MaxRequests: uint32(config.MaxHalfOpenRequests),
		Interval:    0, // Count consecutive failures only
		Timeout:     config.Timeout,
		ReadyToTrip: func(counts gobreaker.Counts) bool {
			return counts.ConsecutiveFailures >= uint32(config.FailureThreshold)
		},
		OnStateChange: func(name string, from gobreaker.State, to gobreaker.State) {
			logger.Info("circuit breaker state changed",
				slog.String("circuit_id", name),
				slog.String("from", stateString(from)),
				slog.String("to", stateString(to)),
			)
		},
	}

	cb := gobreaker.NewCircuitBreaker(cbSettings)

	return &CircuitBreakerAdapter{
		cb:     cb,
		logger: logger,
	}
}

// Execute wraps a function call with circuit breaker protection. If the
// circuit is Open, it immediately returns an error without calling the
// function. If the circuit is Closed or HalfOpen, it calls the function
// and records the result to update the circuit breaker state.
func (a *CircuitBreakerAdapter) Execute(ctx context.Context, fn func(ctx context.Context) error) error {
	_, err := a.cb.Execute(func() (interface{}, error) {
		return nil, fn(ctx)
	})

	if err != nil {
		if err == gobreaker.ErrOpenState {
			return fmt.Errorf("circuit breaker %s is open: %w", a.cb.Name(), err)
		}
		if err == gobreaker.ErrTooManyRequests {
			return fmt.Errorf("circuit breaker %s is half-open with too many requests: %w", a.cb.Name(), err)
		}
		return nil, err
	}

	return nil
}

// GetState returns the current circuit breaker state snapshot for observability.
func (a *CircuitBreakerAdapter) GetState(ctx context.Context) models.CircuitBreakerInfo {
	var state models.CircuitState
	switch a.cb.State() {
	case gobreaker.StateClosed:
		state = models.CircuitStateClosed
	case gobreaker.StateOpen:
		state = models.CircuitStateOpen
	case gobreaker.StateHalfOpen:
		state = models.CircuitStateHalfOpen
	default:
		state = models.CircuitStateClosed
	}

	counts := a.cb.Counts()
	return models.CircuitBreakerInfo{
		Name:         a.cb.Name(),
		State:        state,
		FailureCount: int(counts.ConsecutiveFailures),
		SuccessCount: int(counts.ConsecutiveSuccesses),
	}
}

// Reset forcefully resets the circuit breaker to Closed state. This
// generates a new gobreaker instance to effectively reset it.
func (a *CircuitBreakerAdapter) Reset(ctx context.Context) error {
	cbSettings := gobreaker.Settings{
		Name:     a.cb.Name(),
		Interval: 0,
		Timeout:  30 * time.Second,
		ReadyToTrip: func(counts gobreaker.Counts) bool {
			return counts.ConsecutiveFailures >= 5
		},
	}
	a.cb = gobreaker.NewCircuitBreaker(cbSettings)

	return &models.CircuitBreakerInfo{
		Name:         a.cb.Name(),
		State:        state,
		FailureCount: int(counts.ConsecutiveFailures),
		SuccessCount: int(counts.ConsecutiveSuccesses),
	}, nil
}

// stateString converts a gobreaker.State to a human-readable string.
func stateString(s gobreaker.State) string {
	switch s {
	case gobreaker.StateClosed:
		return "CLOSED"
	case gobreaker.StateOpen:
		return "OPEN"
	case gobreaker.StateHalfOpen:
		return "HALF_OPEN"
	default:
		return "UNKNOWN"
	}
}

// DefaultCircuitConfig returns a sensible default configuration
// for the payment gateway circuit breaker.
func DefaultCircuitConfig(name string) models.CircuitConfig {
	return models.DefaultCircuitConfig(name)
}

// Ensure CircuitBreakerAdapter implements CircuitBreakerPort at compile time.
var _ outbound.CircuitBreakerPort = (*CircuitBreakerAdapter)(nil)
