package inbound

import (
	"context"

	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
)

// ProcessPaymentUseCase handles the creation and authorization of new payments.
// This is the primary entry point for the payment lifecycle, coordinating between
// the payment gateway (via ACL), the circuit breaker, and the persistence layer.
// It enforces idempotency through the IdempotencyKey to prevent double-charging.
type ProcessPaymentUseCase interface {
	Execute(ctx context.Context, cmd ProcessPaymentCommand) (*models.Payment, error)
}

// ProcessPaymentCommand contains all data needed to initiate a payment.
// The IdempotencyKey is mandatory and must be unique per payment attempt.
// Retries with the same key return the original payment result without
// creating a duplicate charge, ensuring safe retry semantics.
type ProcessPaymentCommand struct {
	OrderID        string               `json:"order_id"`
	Amount         models.Money         `json:"amount"`
	Method         models.PaymentMethod `json:"method"`
	CustomerID     string               `json:"customer_id"`
	IdempotencyKey string               `json:"idempotency_key"`
	Metadata       map[string]string    `json:"metadata,omitempty"`
}

// RefundPaymentUseCase processes refunds against completed payments.
// Refunds can be partial or full, and are idempotent via their own
// IdempotencyKey. The use case validates that the payment exists,
// is in a refundable state, and that the refund amount does not
// exceed the remaining refundable balance.
type RefundPaymentUseCase interface {
	Execute(ctx context.Context, cmd RefundPaymentCommand) (*models.Refund, error)
}

// RefundPaymentCommand contains the data needed to initiate a refund.
type RefundPaymentCommand struct {
	PaymentID      string              `json:"payment_id"`
	Amount         models.Money        `json:"amount"`
	Reason         models.RefundReason `json:"reason"`
	IdempotencyKey string              `json:"idempotency_key"`
	Metadata       map[string]string   `json:"metadata,omitempty"`
}

// GetTransactionUseCase retrieves a payment transaction by its ID.
// This supports both customer-facing status checks and internal
// reconciliation workflows. The query returns the full payment
// object including all status transitions and metadata.
type GetTransactionUseCase interface {
	Execute(ctx context.Context, query GetTransactionQuery) (*models.Payment, error)
}

// GetTransactionQuery identifies which transaction to retrieve.
type GetTransactionQuery struct {
	PaymentID string `json:"payment_id"`
}

// ListTransactionsUseCase retrieves a paginated list of transactions
// filtered by customer, status, date range, or other criteria.
// This supports the admin dashboard and financial reconciliation workflows.
type ListTransactionsUseCase interface {
	Execute(ctx context.Context, query ListTransactionsQuery) ([]*models.Payment, string, error)
}

// ListTransactionsQuery contains filter criteria for transaction listing.
type ListTransactionsQuery struct {
	CustomerID string               `json:"customer_id,omitempty"`
	Status     models.PaymentStatus `json:"status,omitempty"`
	FromTime   *string              `json:"from_time,omitempty"`
	ToTime     *string              `json:"to_time,omitempty"`
	PageSize   int                  `json:"page_size,omitempty"`
	Cursor     string               `json:"cursor,omitempty"`
}

// GetCircuitStatusUseCase returns the current state of a circuit breaker
// protecting an external payment gateway. This supports operational
// dashboards and alerting when circuit breakers open unexpectedly.
type GetCircuitStatusUseCase interface {
	Execute(ctx context.Context, query GetCircuitStatusQuery) (*models.CircuitBreakerInfo, error)
}

// GetCircuitStatusQuery identifies which circuit breaker to query.
type GetCircuitStatusQuery struct {
	CircuitName string `json:"circuit_name"`
}
