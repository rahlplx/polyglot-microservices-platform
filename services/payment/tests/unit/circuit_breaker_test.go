package unit

import (
        "context"
        "log/slog"
        "os"
        "testing"
        "time"

        "github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
        "github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/services"
)

// TestCircuitBreakerClosedToOpen verifies that the circuit breaker transitions
// from Closed to Open state after the configured number of consecutive failures.
// This is the core protection mechanism that prevents cascading failures when
// an external gateway becomes unresponsive.
func TestCircuitBreakerClosedToOpen(t *testing.T) {
        logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
        config := models.CircuitConfig{
                Name:                "test-circuit",
                FailureThreshold:    3,
                Timeout:             5 * time.Second,
                MaxHalfOpenRequests: 1,
        }

        cb := services.NewCircuitBreakerService(config, logger)

        // Record failures below threshold.
        cb.RecordFailureForTest()
        cb.RecordFailureForTest()

        info := cb.GetState(nil)
        if info.State != models.CircuitStateClosed {
                t.Errorf("expected CLOSED after 2 failures, got %s", info.State)
        }

        // Third failure should open the circuit.
        cb.RecordFailureForTest()

        info = cb.GetState(nil)
        if info.State != models.CircuitStateOpen {
                t.Errorf("expected OPEN after 3 failures, got %s", info.State)
        }
}

// TestCircuitBreakerOpenRejectsRequests verifies that when the circuit is Open,
// all requests are immediately rejected without calling the protected function.
func TestCircuitBreakerOpenRejectsRequests(t *testing.T) {
        logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
        config := models.CircuitConfig{
                Name:                "test-circuit-reject",
                FailureThreshold:    1,
                Timeout:             1 * time.Hour, // Long timeout so it stays open
                MaxHalfOpenRequests: 1,
        }

        cb := services.NewCircuitBreakerService(config, logger)

        // Trigger open state with one failure.
        cb.RecordFailureForTest()

        // Attempt to execute through the circuit breaker.
        err := cb.Execute(context.Background(), func(_ context.Context) error {
                t.Error("function should not be called when circuit is open")
                return nil
        })

        if err == nil {
                t.Error("expected error when circuit is open")
        }
}

// TestCircuitBreakerSuccessResetsFailures verifies that a successful request
// in Closed state resets the failure counter, preventing accumulation of
// partial failures from triggering an open circuit.
func TestCircuitBreakerSuccessResetsFailures(t *testing.T) {
        logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
        config := models.CircuitConfig{
                Name:                "test-circuit-reset",
                FailureThreshold:    3,
                Timeout:             5 * time.Second,
                MaxHalfOpenRequests: 1,
        }

        cb := services.NewCircuitBreakerService(config, logger)

        // Two failures (below threshold).
        cb.RecordFailureForTest()
        cb.RecordFailureForTest()

        // One success resets the counter.
        cb.RecordSuccessForTest()

        info := cb.GetState(nil)
        if info.State != models.CircuitStateClosed {
                t.Errorf("expected CLOSED after success, got %s", info.State)
        }
        if info.FailureCount != 0 {
                t.Errorf("expected failure count 0 after success, got %d", info.FailureCount)
        }
}
