// Package resilience implements the outbound circuit breaker adapter for
// the Payment service. It uses the sony/gobreaker library to implement
// the CircuitBreakerPort interface, providing Resilience4j-style circuit
// breaker semantics with three states: Closed, Open, and HalfOpen. The
// circuit breaker wraps all calls to the external payment gateway,
// providing automatic fail-fast behavior when the gateway is unavailable.
// Configurable thresholds control when the circuit opens (5 consecutive
// failures) and when it transitions from Open to HalfOpen (30s timeout).
// In HalfOpen state, only 1 probe request is allowed to test recovery.
package resilience

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/sony/gobreaker"

	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/ports/outbound"
	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/services"
)

// CircuitBreakerAdapter implements the CircuitBreakerPort interface using
// the sony/gobreaker library. It wraps the gobreaker.CircuitBreaker with
// the domain-oriented CircuitBreakerPort interface, providing a clean
// boundary between the infrastructure library and the domain services.
// The adapter also maintains a reference to the domain CircuitBreakerService
// for state tracking and event publishing.
type CircuitBreakerAdapter struct {
	cb      *gobreaker.CircuitBreaker
	service *services.CircuitBreakerService
	config  models.CircuitBreakerConfig
	logger  *slog.Logger
}

// NewCircuitBreakerAdapter creates a new circuit breaker adapter with the
// given circuit ID and configuration. It initializes both the gobreaker
// instance and the domain CircuitBreakerService.
func NewCircuitBreakerAdapter(circuitID string, config models.CircuitBreakerConfig, logger *slog.Logger) *CircuitBreakerAdapter {
	if logger == nil {
		logger = slog.Default()
	}

	cbSettings := gobreaker.Settings{
		Name:        circuitID,
		MaxRequests: uint32(config.HalfOpenMaxRequests),
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
	service := services.NewCircuitBreakerService(circuitID, config, logger)

	return &CircuitBreakerAdapter{
		cb:      cb,
		service: service,
		config:  config,
		logger:  logger,
	}
}

// Execute wraps a function call with circuit breaker protection. If the
// circuit is Open, it immediately returns a GatewayUnavailableError
// without calling the function. If the circuit is Closed or HalfOpen,
// it calls the function and records the result to update the circuit
// breaker state. The adapter coordinates between the gobreaker library
// and the domain CircuitBreakerService to keep both in sync.
func (a *CircuitBreakerAdapter) Execute(ctx context.Context, fn func(ctx context.Context) error) error {
	// Check domain service for allow decision first
	if !a.service.AllowRequest() {
		state := a.service.GetState(ctx)
		return &models.GatewayUnavailableError{
			GatewayID:    state.CircuitID,
			CircuitState: state.State.String(),
		}
	}

	// Execute through gobreaker
	_, err := a.cb.Execute(func() (interface{}, error) {
		return nil, fn(ctx)
	})

	if err != nil {
		// Record failure in domain service
		a.service.RecordFailure()

		// Check if this is a gobreaker open-circuit error
		if err == gobreaker.ErrOpenState {
			state := a.service.GetState(ctx)
			return &models.GatewayUnavailableError{
				GatewayID:    state.CircuitID,
				CircuitState: "OPEN",
			}
		}
		if err == gobreaker.ErrTooManyRequests {
			state := a.service.GetState(ctx)
			return &models.GatewayUnavailableError{
				GatewayID:    state.CircuitID,
				CircuitState: "HALF_OPEN",
			}
		}
		return err
	}

	// Record success in domain service
	a.service.RecordSuccess()
	return nil
}

// GetState returns the current circuit breaker state from the domain service.
func (a *CircuitBreakerAdapter) GetState(ctx context.Context) models.CircuitBreakerState {
	return a.service.GetState(ctx)
}

// Reset forcefully resets the circuit breaker to Closed state. This
// resets both the gobreaker instance and the domain service.
func (a *CircuitBreakerAdapter) Reset(ctx context.Context) error {
	// Reset the domain service
	if err := a.service.Reset(ctx); err != nil {
		return err
	}

	// Generate a new gobreaker instance to effectively reset it
	cbSettings := gobreaker.Settings{
		Name:        a.cb.Name(),
		MaxRequests: uint32(a.config.HalfOpenMaxRequests),
		Interval:    0,
		Timeout:     a.config.Timeout,
		ReadyToTrip: func(counts gobreaker.Counts) bool {
			return counts.ConsecutiveFailures >= uint32(a.config.FailureThreshold)
		},
	}
	a.cb = gobreaker.NewCircuitBreaker(cbSettings)

	a.logger.Info("circuit breaker reset to closed state",
		slog.String("circuit_id", a.cb.Name()),
	)
	return nil
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

// DefaultCircuitBreakerConfig returns a sensible default configuration
// for the payment gateway circuit breaker. The defaults are tuned for
// the 99.99% SLO target: 5 consecutive failures trigger Open, 30s
// timeout before HalfOpen, and 1 probe request allowed in HalfOpen
// to test whether the gateway has recovered before closing the circuit.
func DefaultCircuitBreakerConfig() models.CircuitBreakerConfig {
	return models.CircuitBreakerConfig{
		FailureThreshold:     5,
		SuccessThreshold:     3,
		Timeout:              30 * time.Second,
		HalfOpenMaxRequests:  1,
	}
}

// Ensure CircuitBreakerAdapter implements CircuitBreakerPort at compile time.
var _ outbound.CircuitBreakerPort = (*CircuitBreakerAdapter)(nil)
