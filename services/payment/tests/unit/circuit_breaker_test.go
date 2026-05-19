package unit

import (
	"testing"
	"time"

	"github.com/gstack/payment-service/domain/models"
	"github.com/gstack/payment-service/domain/services"
	"log/slog"
	"os"
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

	info, _ := cb.GetState(nil)
	if info.State != models.CircuitStateClosed {
		t.Errorf("expected CLOSED after 2 failures, got %s", info.State)
	}

	// Third failure should open the circuit.
	cb.RecordFailureForTest()

	info, _ = cb.GetState(nil)
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
	_, err := cb.Execute(nil, func() (interface{}, error) {
		t.Error("function should not be called when circuit is open")
		return nil, nil
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

	info, _ := cb.GetState(nil)
	if info.State != models.CircuitStateClosed {
		t.Errorf("expected CLOSED after success, got %s", info.State)
	}
	if info.FailureCount != 0 {
		t.Errorf("expected failure count 0 after success, got %d", info.FailureCount)
	}
}
