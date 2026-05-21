package models

import "time"

// CircuitState represents the state of a circuit breaker protecting an external
// service call. The circuit breaker pattern prevents cascading failures by
// stopping requests to a failing service, giving it time to recover. This
// implementation follows the standard three-state model used by gobreaker and
// similar libraries, with configurable thresholds and timeouts.
type CircuitState string

const (
        CircuitStateClosed   CircuitState = "CLOSED"
        CircuitStateOpen     CircuitState = "OPEN"
        CircuitStateHalfOpen CircuitState = "HALF_OPEN"
)

// CircuitConfig holds the configuration parameters for a circuit breaker instance.
// These parameters control the sensitivity and recovery behavior of the circuit.
// Default values are chosen based on production experience with payment gateways:
// 5 consecutive failures trigger open state, 30 seconds before retry attempt,
// and 1 successful request in half-open to close the circuit again.
type CircuitConfig struct {
        Name                   string        `json:"name"`
        FailureThreshold       int           `json:"failure_threshold"`
        Timeout                time.Duration `json:"timeout"`
        MaxHalfOpenRequests    int           `json:"max_half_open_requests"`
        OnStateChange          func(from, to CircuitState) `json:"-"`
}

// DefaultCircuitConfig returns production-tested defaults for payment gateway
// circuit breakers. The 5-failure threshold balances sensitivity against
// transient network issues, while the 30-second timeout gives external
// services adequate recovery time without causing excessive latency.
func DefaultCircuitConfig(name string) CircuitConfig {
        return CircuitConfig{
                Name:                name,
                FailureThreshold:    5,
                Timeout:             30 * time.Second,
                MaxHalfOpenRequests: 1,
        }
}

// CircuitBreakerInfo holds a snapshot of the circuit breaker's current state
// for observability and debugging. This information is exposed via OTel metrics
// and the admin API to help operators understand gateway health at a glance.
type CircuitBreakerInfo struct {
        Name            string       `json:"name"`
        State           CircuitState `json:"state"`
        FailureCount    int          `json:"failure_count"`
        SuccessCount    int          `json:"success_count"`
        LastFailureTime *time.Time   `json:"last_failure_time,omitempty"`
        LastStateChange *time.Time   `json:"last_state_change,omitempty"`
}

// CircuitBreakerState holds a comprehensive snapshot of the circuit breaker
// including configuration and runtime statistics. This is used by the
// CircuitBreakerPort to return full state information to callers.
type CircuitBreakerState struct {
        Config       CircuitConfig    `json:"config"`
        Info         CircuitBreakerInfo `json:"info"`
}

// PendingOperation represents a payment operation that has been recorded
// but not yet submitted to the external gateway. These operations are
// persisted to allow retry after circuit breaker recovery.
type PendingOperation struct {
        ID          string        `json:"id"`
        PaymentID   string        `json:"payment_id"`
        Operation   string        `json:"operation"` // AUTHORIZE, CAPTURE, REFUND, VOID
        AttemptedAt time.Time     `json:"attempted_at"`
        RetryCount  int           `json:"retry_count"`
        MaxRetries  int           `json:"max_retries"`
}

// CircuitBreakerEvent represents a state change event that can be published
// to the event bus for cross-service awareness. When a payment gateway circuit
// opens, downstream services need to know so they can implement fallback
// strategies rather than attempting payments that will immediately fail.
type CircuitBreakerEvent struct {
        CircuitName string       `json:"circuit_name"`
        FromState   CircuitState `json:"from_state"`
        ToState     CircuitState `json:"to_state"`
        Timestamp   time.Time    `json:"timestamp"`
        Reason      string       `json:"reason,omitempty"`
}
