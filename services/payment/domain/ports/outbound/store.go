// Package outbound defines the driven port interfaces for the Payment domain.
// This file provides the TransactionRepository interface for payment and
// refund persistence. The repository manages the complete lifecycle of
// payment records, refund records, and the transactional outbox. All
// database operations that modify payment state must be performed within
// a transaction to ensure consistency between the payment record and the
// outbox events.
package outbound

import (
	"context"

	"github.com/gstack/payment-service/domain/models"
)

// TransactionRepository defines the interface for persisting payment and
// refund records. The repository uses PostgreSQL's advisory locks for
// concurrent payment processing, preventing two goroutines from processing
// the same payment simultaneously. The outbox table follows the same
// pattern as the Order service: events are written to the outbox in the
// same transaction as the payment state change, and a relay process
// publishes them to Kafka.
type TransactionRepository interface {
	// Save persists a payment record. If a payment with the same ID already
	// exists, it updates the existing record using optimistic concurrency
	// control (version check). Returns the persisted payment with its
	// incremented version, or an error if the version conflict indicates
	// a concurrent modification.
	Save(ctx context.Context, payment *models.Payment) error

	// FindByID retrieves a payment by its unique identifier. Returns
	// the payment with full state history, or an error if not found.
	FindByID(ctx context.Context, paymentID string) (*models.Payment, error)

	// FindByOrderID retrieves all payments associated with the given
	// order ID. An order may have multiple payments if the initial
	// payment failed and was retried with a different payment method.
	FindByOrderID(ctx context.Context, orderID string) ([]models.Payment, error)

	// FindByGatewayReference looks up a payment by its external gateway
	// reference. This is used for reconciliation and for processing
	// asynchronous gateway callbacks (webhooks).
	FindByGatewayReference(ctx context.Context, gatewayRef string) (*models.Payment, error)

	// FindByIdempotencyKey looks up a payment by its idempotency key.
	// This is used to prevent duplicate charges by returning the
	// existing payment when a retry occurs with the same key.
	FindByIdempotencyKey(ctx context.Context, key string) (*models.Payment, error)

	// SaveRefund persists a refund record linked to its parent payment.
	// The refund must reference an existing, captured payment. Returns
	// an error if the parent payment does not exist or is not in a
	// refundable state.
	SaveRefund(ctx context.Context, refund *models.Refund) error

	// FindRefundByID retrieves a refund by its unique identifier.
	FindRefundByID(ctx context.Context, refundID string) (*models.Refund, error)

	// FindRefundsByPaymentID retrieves all refunds for a given payment.
	FindRefundsByPaymentID(ctx context.Context, paymentID string) ([]models.Refund, error)

	// FindPendingOperations retrieves all operations that are pending
	// gateway submission. This is used by the retry processor to
	// resubmit operations when the circuit breaker allows traffic.
	FindPendingOperations(ctx context.Context) ([]models.PendingOperation, error)

	// SavePendingOperation persists a pending operation for later retry.
	SavePendingOperation(ctx context.Context, op *models.PendingOperation) error

	// SaveOutboxEvent writes an event to the outbox table within the
	// same transaction as the payment state change. The outbox relay
	// process will publish this event to Kafka asynchronously.
	SaveOutboxEvent(ctx context.Context, eventType string, payload []byte, aggregateID string) error
}
