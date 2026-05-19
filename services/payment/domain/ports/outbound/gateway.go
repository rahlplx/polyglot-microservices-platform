package outbound

import (
	"context"

	"github.com/gstack/payment-service/domain/models"
)

// PaymentGatewayPort defines the interface for communicating with external payment
// gateways (Stripe, Adyen, etc.). This port is the ACL boundary — implementations
// live in the adapters/outbound/gateway/ directory and translate between the domain's
// generic payment model and the vendor-specific API. No vendor SDK types leak through
// this interface, maintaining the hexagonal architecture boundary. The circuit breaker
// wraps all calls through this port to protect against gateway outages.
type PaymentGatewayPort interface {
	// Authorize reserves the funds on the customer's payment instrument.
	// Returns a gateway transaction ID that must be stored for later capture.
	Authorize(ctx context.Context, payment *models.Payment) (gatewayTxnID string, err error)

	// Capture completes a previously authorized payment, transferring funds.
	Capture(ctx context.Context, payment *models.Payment) error

	// Refund returns funds to the customer for a previously captured payment.
	Refund(ctx context.Context, refund *models.Refund, originalPayment *models.Payment) (gatewayRefundID string, err error)

	// Void cancels an authorization without capturing, releasing held funds.
	Void(ctx context.Context, payment *models.Payment) error
}

// TransactionRepository persists payment and refund records. The repository follows
// the outbox pattern — payment events are written to an outbox table in the same
// database transaction as the payment record, ensuring at-least-once delivery
// through the CDC relay without distributed transaction coordination.
type TransactionRepository interface {
	// SavePayment persists a new payment record.
	SavePayment(ctx context.Context, payment *models.Payment) error

	// UpdatePayment updates an existing payment (status transitions, metadata).
	UpdatePayment(ctx context.Context, payment *models.Payment) error

	// GetPayment retrieves a payment by its unique ID.
	GetPayment(ctx context.Context, id string) (*models.Payment, error)

	// GetPaymentByIdempotencyKey retrieves a payment by its idempotency key.
	// Returns nil if no payment exists with this key, enabling idempotent processing.
	GetPaymentByIdempotencyKey(ctx context.Context, key string) (*models.Payment, error)

	// ListPayments retrieves payments filtered by criteria with cursor-based pagination.
	ListPayments(ctx context.Context, customerID string, status models.PaymentStatus, cursor string, pageSize int) ([]*models.Payment, string, error)

	// SaveRefund persists a new refund record associated with a payment.
	SaveRefund(ctx context.Context, refund *models.Refund) error

	// GetRefund retrieves a refund by its unique ID.
	GetRefund(ctx context.Context, id string) (*models.Refund, error)

	// SaveOutboxEvent persists an event to the outbox table for CDC relay pickup.
	SaveOutboxEvent(ctx context.Context, eventType string, aggregateID string, payload []byte) error
}

// EventPublisher publishes domain events to the message bus. In production, this
// is implemented by the CDC relay reading from the outbox table. The publisher
// interface exists for testing and for direct publishing in development mode.
type EventPublisher interface {
	// PublishPaymentEvent publishes a payment lifecycle event.
	PublishPaymentEvent(ctx context.Context, eventType string, payment *models.Payment) error

	// PublishRefundEvent publishes a refund lifecycle event.
	PublishRefundEvent(ctx context.Context, eventType string, refund *models.Refund) error

	// PublishCircuitEvent publishes a circuit breaker state change event.
	PublishCircuitEvent(ctx context.Context, event models.CircuitBreakerEvent) error
}

// CircuitBreakerPort defines the interface for circuit breaker operations.
// The implementation wraps sony/gobreaker and provides state transitions,
// success/failure recording, and current state querying. This port allows
// the domain service to check circuit state before attempting gateway calls
// and to record outcomes after gateway responses.
type CircuitBreakerPort interface {
	// Execute runs the given function through the circuit breaker.
	// If the circuit is open, it returns an error immediately without calling fn.
	Execute(ctx context.Context, fn func() (interface{}, error)) (interface{}, error)

	// GetState returns the current circuit breaker state snapshot.
	GetState(ctx context.Context) (*models.CircuitBreakerInfo, error)
}
