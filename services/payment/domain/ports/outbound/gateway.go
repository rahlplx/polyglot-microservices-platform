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
