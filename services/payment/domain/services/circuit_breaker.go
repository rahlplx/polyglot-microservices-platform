package services

import (
        "context"
        "fmt"
        "log/slog"
        "sync"
        "time"

        "github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
)

// CircuitBreakerService implements a state machine for protecting external service calls.
// It follows the standard Closed → Open → HalfOpen pattern with configurable thresholds.
// When failures exceed the threshold in Closed state, the circuit opens and rejects
// all calls immediately. After a timeout period, the circuit transitions to HalfOpen,
// allowing a limited number of probe requests through. Successful probes close the
// circuit; failed probes reopen it. This implementation is thread-safe and suitable
// for concurrent use in a high-throughput payment service.
type CircuitBreakerService struct {
        mu                 sync.RWMutex
        name               string
        state              models.CircuitState
        failureCount       int
        successCount       int
        failureThreshold   int
        timeout            time.Duration
        maxHalfOpenReqs    int
        halfOpenSuccesses  int
        lastFailureTime    *time.Time
        lastStateChange    time.Time
        onStateChange      func(from, to models.CircuitState)
        logger             *slog.Logger
}

// NewCircuitBreakerService creates a new circuit breaker with the given configuration.
// The circuit starts in Closed state and transitions based on the configured thresholds.
func NewCircuitBreakerService(config models.CircuitConfig, logger *slog.Logger) *CircuitBreakerService {
        now := time.Now().UTC()
        return &CircuitBreakerService{
                name:             config.Name,
                state:            models.CircuitStateClosed,
                failureThreshold: config.FailureThreshold,
                timeout:          config.Timeout,
                maxHalfOpenReqs:  config.MaxHalfOpenRequests,
                lastStateChange:  now,
                onStateChange:    config.OnStateChange,
                logger:           logger,
        }
}

// Execute runs the given function through the circuit breaker protection.
// If the circuit is Open, it returns an error immediately. If HalfOpen,
// it allows limited requests through. All outcomes are recorded to update
// the circuit state according to the configured rules.
func (cb *CircuitBreakerService) Execute(ctx context.Context, fn func(ctx context.Context) error) error {
        // Check current state and possibly transition from Open to HalfOpen.
        state := cb.beforeRequest()
        switch state {
        case models.CircuitStateOpen:
                return fmt.Errorf("circuit breaker %s is open", cb.name)
        case models.CircuitStateHalfOpen:
                // Allow the request through in half-open state as a probe.
        default:
                // Closed state: allow all requests through.
        }

        err := fn(ctx)
        if err != nil {
                cb.recordFailure()
                return err
        }

        cb.recordSuccess()
        return nil
}

// GetState returns a snapshot of the circuit breaker's current state for observability.
func (cb *CircuitBreakerService) GetState(ctx context.Context) models.CircuitBreakerInfo {
        cb.mu.RLock()
        defer cb.mu.RUnlock()

        return models.CircuitBreakerInfo{
                Name:            cb.name,
                State:           cb.state,
                FailureCount:    cb.failureCount,
                SuccessCount:    cb.successCount,
                LastFailureTime: cb.lastFailureTime,
                LastStateChange: &cb.lastStateChange,
        }
}

// Reset forcefully resets the circuit breaker to Closed state.
// This is an administrative operation that should be used with caution.
func (cb *CircuitBreakerService) Reset(ctx context.Context) error {
        cb.mu.Lock()
        defer cb.mu.Unlock()

        from := cb.state
        cb.state = models.CircuitStateClosed
        cb.failureCount = 0
        cb.successCount = 0
        cb.halfOpenSuccesses = 0
        cb.lastStateChange = time.Now().UTC()

        cb.logger.Info("circuit breaker reset to closed state",
                "circuit", cb.name,
                "from", from,
        )

        if cb.onStateChange != nil {
                cb.onStateChange(from, models.CircuitStateClosed)
        }

        return nil
}

// beforeRequest checks and potentially transitions the circuit state before
// allowing a request. It handles the Open → HalfOpen transition based on timeout.
func (cb *CircuitBreakerService) beforeRequest() models.CircuitState {
        cb.mu.Lock()
        defer cb.mu.Unlock()

        if cb.state == models.CircuitStateOpen {
                // Check if enough time has passed to transition to half-open.
                if time.Since(cb.lastStateChange) >= cb.timeout {
                        cb.transitionTo(models.CircuitStateHalfOpen)
                        cb.halfOpenSuccesses = 0
                }
        }

        return cb.state
}

// recordFailure increments the failure counter and potentially opens the circuit.
func (cb *CircuitBreakerService) recordFailure() {
        cb.mu.Lock()
        defer cb.mu.Unlock()

        now := time.Now().UTC()
        cb.lastFailureTime = &now

        switch cb.state {
        case models.CircuitStateClosed:
                cb.failureCount++
                if cb.failureCount >= cb.failureThreshold {
                        cb.transitionTo(models.CircuitStateOpen)
                }
        case models.CircuitStateHalfOpen:
                // Any failure in half-open immediately reopens the circuit.
                cb.transitionTo(models.CircuitStateOpen)
        }
}

// recordSuccess increments the success counter and potentially closes the circuit.
func (cb *CircuitBreakerService) recordSuccess() {
        cb.mu.Lock()
        defer cb.mu.Unlock()

        cb.successCount++

        switch cb.state {
        case models.CircuitStateHalfOpen:
                cb.halfOpenSuccesses++
                if cb.halfOpenSuccesses >= cb.maxHalfOpenReqs {
                        cb.transitionTo(models.CircuitStateClosed)
                        cb.failureCount = 0
                }
        case models.CircuitStateClosed:
                // Reset failure count on success — partial failures don't accumulate.
                cb.failureCount = 0
        }
}

// transitionTo changes the circuit state and invokes the state change callback.
func (cb *CircuitBreakerService) transitionTo(newState models.CircuitState) {
        from := cb.state
        cb.state = newState
        cb.lastStateChange = time.Now().UTC()

        cb.logger.Info("circuit breaker state changed",
                "circuit", cb.name,
                "from", from,
                "to", newState,
        )

        if cb.onStateChange != nil {
                cb.onStateChange(from, newState)
        }
}

// RecordFailureForTest exports the unexported recordFailure method for unit testing.
// This allows tests to directly manipulate the failure counter without executing
// a function through the circuit breaker.
func (cb *CircuitBreakerService) RecordFailureForTest() {
        cb.recordFailure()
}

// RecordSuccessForTest exports the unexported recordSuccess method for unit testing.
// This allows tests to verify that a successful request resets the failure counter.
func (cb *CircuitBreakerService) RecordSuccessForTest() {
        cb.recordSuccess()
}
