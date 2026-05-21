// Package resilience implements the outbound circuit breaker adapter for
// the Payment service. It uses the sony/gobreaker library to implement
// the CircuitBreakerPort interface, providing Resilience4j-style circuit
// breaker semantics with three states: Closed, Open, and HalfOpen.
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
// the sony/gobreaker library. It wraps gobreaker.CircuitBreaker with the
// domain-oriented CircuitBreakerPort interface.
type CircuitBreakerAdapter struct {
	cb     *gobreaker.CircuitBreaker
	config models.CircuitConfig
	logger *slog.Logger
}

// NewCircuitBreakerAdapter creates a new circuit breaker adapter with the
// given circuit configuration.
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
		config: config,
		logger: logger,
	}
}

// Execute wraps a function call with circuit breaker protection. If the
// circuit is Open, it immediately returns an error without calling fn.
// If the circuit is Closed or HalfOpen, it calls the function and records
// the result to update the circuit breaker state.
func (a *CircuitBreakerAdapter) Execute(ctx context.Context, fn func() (interface{}, error)) (interface{}, error) {
	result, err := a.cb.Execute(func() (interface{}, error) {
		return fn()
	})

	if err != nil {
		if err == gobreaker.ErrOpenState {
			return nil, fmt.Errorf("circuit breaker %s is open: gateway unavailable", a.cb.Name())
		}
		if err == gobreaker.ErrTooManyRequests {
			return nil, fmt.Errorf("circuit breaker %s is half-open: too many requests", a.cb.Name())
		}
		return nil, err
	}

	return result, nil
}

// GetState returns the current circuit breaker state for observability.
func (a *CircuitBreakerAdapter) GetState(ctx context.Context) (*models.CircuitBreakerInfo, error) {
	var state models.CircuitState
	switch a.cb.State() {
	case gobreaker.StateClosed:
		state = models.CircuitStateClosed
	case gobreaker.StateOpen:
		state = models.CircuitStateOpen
	case gobreaker.StateHalfOpen:
		state = models.CircuitStateHalfOpen
	}

	counts := a.cb.Counts()

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

// DefaultCircuitConfig returns a sensible default configuration for the
// payment gateway circuit breaker.
func DefaultCircuitConfig() models.CircuitConfig {
	return models.CircuitConfig{
		Name:                "payment-gateway",
		FailureThreshold:    5,
		Timeout:             30 * time.Second,
		MaxHalfOpenRequests: 1,
	}
}

// Ensure CircuitBreakerAdapter implements CircuitBreakerPort at compile time.
var _ outbound.CircuitBreakerPort = (*CircuitBreakerAdapter)(nil)
