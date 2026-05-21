package outbound

import (
	"context"

	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
)

// PaymentGatewayPort defines the interface for communicating with external payment
// gateways (Stripe, Adyen, etc.). This port is the ACL boundary — implementations
// live in the adapters/outbound/gateway/ directory and translate between the domain's
// generic payment model and the vendor-specific API. No vendor SDK types leak through
// this interface, maintaining the hexagonal architecture boundary.
type PaymentGatewayPort interface {
	Authorize(ctx context.Context, payment *models.Payment) (gatewayTxnID string, err error)
	Capture(ctx context.Context, payment *models.Payment) error
	Refund(ctx context.Context, refund *models.Refund, originalPayment *models.Payment) (gatewayRefundID string, err error)
	Void(ctx context.Context, payment *models.Payment) error
}

// TransactionRepository persists payment and refund records. The repository follows
// the outbox pattern — payment events are written to an outbox table in the same
// database transaction as the payment record, ensuring at-least-once delivery
// through the CDC relay without distributed transaction coordination.
type TransactionRepository interface {
	SavePayment(ctx context.Context, payment *models.Payment) error
	UpdatePayment(ctx context.Context, payment *models.Payment) error
	GetPayment(ctx context.Context, id string) (*models.Payment, error)
	GetPaymentByIdempotencyKey(ctx context.Context, key string) (*models.Payment, error)
	ListPayments(ctx context.Context, customerID string, status models.PaymentStatus, cursor string, pageSize int) ([]*models.Payment, string, error)
	SaveRefund(ctx context.Context, refund *models.Refund) error
	GetRefund(ctx context.Context, id string) (*models.Refund, error)
	FindPendingOperations(ctx context.Context) ([]models.PendingOperation, error)
	SavePendingOperation(ctx context.Context, op *models.PendingOperation) error
	SaveOutboxEvent(ctx context.Context, eventType string, aggregateID string, payload []byte) error
}

// CircuitBreakerPort defines the interface for circuit breaker operations.
// The implementation wraps sony/gobreaker and provides state transitions,
// success/failure recording, and current state querying.
type CircuitBreakerPort interface {
	Execute(ctx context.Context, fn func() (interface{}, error)) (interface{}, error)
	GetState(ctx context.Context) (*models.CircuitBreakerInfo, error)
}

// EventPublisher publishes domain events to the message bus. In production, this
// is implemented by the CDC relay reading from the outbox table.
type EventPublisher interface {
	PublishPaymentEvent(ctx context.Context, eventType string, payment *models.Payment) error
	PublishRefundEvent(ctx context.Context, eventType string, refund *models.Refund) error
	PublishCircuitEvent(ctx context.Context, event models.CircuitBreakerEvent) error
}
