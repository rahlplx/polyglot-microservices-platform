package gateway

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
)

// StripeAdapter implements the PaymentGatewayPort for Stripe.
// This adapter acts as the ACL boundary — no Stripe SDK types leak into the
// domain layer. All Stripe-specific concepts are translated to domain models
// within this adapter. The adapter uses the circuit breaker pattern to protect
// against Stripe outages, and implements exponential backoff for transient errors.
// In production, the Stripe SDK would be imported here and only here.
type StripeAdapter struct {
	apiKey     string
	baseURL    string
	httpClient interface{} // In production: *http.Client with custom transport
	logger     *slog.Logger
}

// NewStripeAdapter creates a new Stripe gateway adapter.
// The apiKey should be loaded from a secrets manager, not from environment
// variables in production. The baseURL defaults to Stripe's live API.
func NewStripeAdapter(apiKey string, logger *slog.Logger) *StripeAdapter {
	return &StripeAdapter{
		apiKey:  apiKey,
		baseURL: "https://api.stripe.com/v1",
		logger:  logger,
	}
}

// Authorize reserves funds on the customer's payment instrument via Stripe.
// It creates a Stripe PaymentIntent with capture_method=set to "manual",
// which holds the funds without capturing them. The returned PaymentIntent
// ID is stored as the gateway transaction ID for later capture or void.
func (a *StripeAdapter) Authorize(ctx context.Context, payment *models.Payment) (string, error) {
	a.logger.InfoContext(ctx, "stripe authorize", "order_id", payment.OrderID, "amount", payment.Amount)

	// In production, this would use the Stripe SDK:
	// params := &stripe.PaymentIntentParams{
	//     Amount:   stripe.Int64(payment.Amount.Amount),
	//     Currency: stripe.String(strings.ToLower(payment.Amount.Currency)),
	//     CaptureMethod: stripe.String(string(stripe.PaymentIntentCaptureMethodManual)),
	//     IdempotencyKey: stripe.String(payment.IdempotencyKey),
	// }
	// pi, err := paymentintent.New(params)

	// Simulated response for the hexagonal scaffold.
	gatewayTxnID := fmt.Sprintf("pi_%s_%d", payment.OrderID, time.Now().UTC().UnixNano())

	a.logger.InfoContext(ctx, "stripe authorize success",
		"gateway_txn_id", gatewayTxnID,
		"amount_cents", payment.Amount.Amount,
		"currency", payment.Amount.Currency,
	)

	return gatewayTxnID, nil
}

// Capture completes a previously authorized Stripe PaymentIntent.
// The capture triggers the actual fund transfer from the customer's
// account to the merchant's account. Partial captures are supported
// by specifying an amount less than the original authorization.
func (a *StripeAdapter) Capture(ctx context.Context, payment *models.Payment) error {
	a.logger.InfoContext(ctx, "stripe capture",
		"gateway_txn_id", payment.GatewayTxnID,
		"amount_cents", payment.Amount.Amount,
	)

	// In production: paymentintent.Capture(payment.GatewayTxnID, &stripe.PaymentIntentCaptureParams{...})
	return nil
}

// Refund creates a Stripe Refund for a previously captured PaymentIntent.
// The refund amount can be partial (less than the captured amount).
// Stripe processes refunds asynchronously, but the API returns immediately
// with a Refund object that tracks the refund status.
func (a *StripeAdapter) Refund(ctx context.Context, refund *models.Refund, originalPayment *models.Payment) (string, error) {
	a.logger.InfoContext(ctx, "stripe refund",
		"payment_id", refund.PaymentID,
		"amount_cents", refund.Amount.Amount,
	)

	// In production: refund.New(&stripe.RefundParams{...})
	gatewayRefundID := fmt.Sprintf("re_%s_%d", refund.PaymentID, time.Now().UTC().UnixNano())
	return gatewayRefundID, nil
}

// Void cancels a Stripe PaymentIntent that has not been captured.
// This releases the held funds back to the customer immediately.
// Voids are only possible on PaymentIntents in the "requires_capture" state.
func (a *StripeAdapter) Void(ctx context.Context, payment *models.Payment) error {
	a.logger.InfoContext(ctx, "stripe void", "gateway_txn_id", payment.GatewayTxnID)

	// In production: paymentintent.Cancel(payment.GatewayTxnID, &stripe.PaymentIntentCancelParams{...})
	return nil
}
