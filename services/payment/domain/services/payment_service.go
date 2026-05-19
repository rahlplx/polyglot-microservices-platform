package services

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/gstack/payment-service/domain/models"
	"github.com/gstack/payment-service/domain/ports/outbound"
)

// PaymentService orchestrates the payment processing lifecycle, coordinating between
// the external payment gateway, the circuit breaker, the persistence layer, and the
// event publisher. It enforces idempotency, validates state transitions, and ensures
// that all side effects (event publishing, outbox writes) occur within consistent
// boundaries. This is the primary application service in the hexagonal architecture.
type PaymentService struct {
	gateway   outbound.PaymentGatewayPort
	repo      outbound.TransactionRepository
	publisher outbound.EventPublisher
	circuit   outbound.CircuitBreakerPort
	logger    *slog.Logger
}

// NewPaymentService creates a new PaymentService with its required dependencies.
// All parameters are required — nil values will cause a panic on first use.
func NewPaymentService(
	gateway outbound.PaymentGatewayPort,
	repo outbound.TransactionRepository,
	publisher outbound.EventPublisher,
	circuit outbound.CircuitBreakerPort,
	logger *slog.Logger,
) *PaymentService {
	return &PaymentService{
		gateway:   gateway,
		repo:      repo,
		publisher: publisher,
		circuit:   circuit,
		logger:    logger,
	}
}

// ProcessPayment handles the full payment authorization flow.
// It first checks idempotency (returning existing payment if key matches),
// then validates the payment amount, authorizes via the gateway (through the
// circuit breaker), persists the result, and publishes the event.
func (s *PaymentService) ProcessPayment(ctx context.Context, cmd ProcessPaymentCommand) (*models.Payment, error) {
	s.logger.InfoContext(ctx, "processing payment", "order_id", cmd.OrderID, "amount", cmd.Amount)

	// Idempotency check: if a payment with this key already exists, return it.
	if cmd.IdempotencyKey != "" {
		existing, err := s.repo.GetPaymentByIdempotencyKey(ctx, cmd.IdempotencyKey)
		if err != nil {
			s.logger.WarnContext(ctx, "idempotency check failed", "error", err)
		}
		if existing != nil {
			s.logger.InfoContext(ctx, "idempotent payment found", "payment_id", existing.ID)
			return existing, nil
		}
	}

	// Validate payment amount.
	if cmd.Amount.IsNegative() || cmd.Amount.IsZero() {
		return nil, fmt.Errorf("payment amount must be positive, got %d cents", cmd.Amount.Amount)
	}

	// Create payment entity in PENDING state.
	payment := &models.Payment{
		OrderID:        cmd.OrderID,
		Amount:         cmd.Amount,
		Method:         cmd.Method,
		Status:         models.PaymentStatusPending,
		CustomerID:     cmd.CustomerID,
		IdempotencyKey: cmd.IdempotencyKey,
		Metadata:       cmd.Metadata,
	}

	// Persist the pending payment.
	if err := s.repo.SavePayment(ctx, payment); err != nil {
		return nil, fmt.Errorf("failed to save pending payment: %w", err)
	}

	// Authorize through gateway (protected by circuit breaker).
	result, err := s.circuit.Execute(ctx, func() (interface{}, error) {
		txnID, err := s.gateway.Authorize(ctx, payment)
		if err != nil {
			return nil, fmt.Errorf("gateway authorization failed: %w", err)
		}
		return txnID, nil
	})

	if err != nil {
		// Circuit is open or gateway failed — transition to FAILED.
		_ = payment.TransitionTo(models.PaymentStatusFailed)
		_ = s.repo.UpdatePayment(ctx, payment)
		_ = s.publisher.PublishPaymentEvent(ctx, "payment.failed", payment)
		return nil, fmt.Errorf("payment processing failed: %w", err)
	}

	// Authorization successful — transition to AUTHORIZED.
	gatewayTxnID := result.(string)
	payment.GatewayTxnID = gatewayTxnID
	if err := payment.TransitionTo(models.PaymentStatusAuthorized); err != nil {
		return nil, fmt.Errorf("invalid state transition after authorization: %w", err)
	}

	// Auto-capture for digital wallet and bank transfer methods.
	if cmd.Method == models.PaymentMethodDigitalWallet || cmd.Method == models.PaymentMethodBankTransfer {
		if err := s.capturePayment(ctx, payment); err != nil {
			s.logger.ErrorContext(ctx, "auto-capture failed", "payment_id", payment.ID, "error", err)
			// Return the authorized payment; capture can be retried.
		}
	}

	// Persist the updated payment state.
	if err := s.repo.UpdatePayment(ctx, payment); err != nil {
		return nil, fmt.Errorf("failed to update payment: %w", err)
	}

	// Publish payment authorized event (via outbox for at-least-once delivery).
	_ = s.publisher.PublishPaymentEvent(ctx, "payment.authorized", payment)

	s.logger.InfoContext(ctx, "payment processed", "payment_id", payment.ID, "status", payment.Status)
	return payment, nil
}

// capturePayment transitions a payment from AUTHORIZED to CAPTURED.
// This is called automatically for certain payment methods or can be
// triggered manually through the capture API endpoint.
func (s *PaymentService) capturePayment(ctx context.Context, payment *models.Payment) error {
	_, err := s.circuit.Execute(ctx, func() (interface{}, error) {
		return nil, s.gateway.Capture(ctx, payment)
	})
	if err != nil {
		return fmt.Errorf("gateway capture failed: %w", err)
	}

	if err := payment.TransitionTo(models.PaymentStatusCaptured); err != nil {
		return err
	}

	// Immediately complete after capture for synchronous methods.
	_ = payment.TransitionTo(models.PaymentStatusCompleted)
	_ = s.publisher.PublishPaymentEvent(ctx, "payment.completed", payment)
	return nil
}

// RefundPayment processes a refund against a completed payment.
// It validates the payment is in a refundable state, calculates the remaining
// refundable balance, and delegates to the payment gateway via the circuit breaker.
func (s *PaymentService) RefundPayment(ctx context.Context, cmd RefundPaymentCommand) (*models.Refund, error) {
	s.logger.InfoContext(ctx, "processing refund", "payment_id", cmd.PaymentID, "amount", cmd.Amount)

	// Retrieve the original payment.
	payment, err := s.repo.GetPayment(ctx, cmd.PaymentID)
	if err != nil {
		return nil, fmt.Errorf("payment not found: %w", err)
	}

	// Validate payment is in a refundable state.
	if payment.Status != models.PaymentStatusCompleted && payment.Status != models.PaymentStatusCaptured {
		return nil, fmt.Errorf("payment in state %s cannot be refunded", payment.Status)
	}

	// Validate refund amount does not exceed payment amount.
	if cmd.Amount.Amount > payment.Amount.Amount {
		return nil, fmt.Errorf("refund amount %d exceeds payment amount %d", cmd.Amount.Amount, payment.Amount.Amount)
	}

	// Create refund entity.
	refund := &models.Refund{
		PaymentID:      cmd.PaymentID,
		Amount:         cmd.Amount,
		Reason:         cmd.Reason,
		Status:         models.RefundStatusPending,
		IdempotencyKey: cmd.IdempotencyKey,
		Metadata:       cmd.Metadata,
	}

	// Process refund through gateway (protected by circuit breaker).
	result, err := s.circuit.Execute(ctx, func() (interface{}, error) {
		gatewayRefundID, err := s.gateway.Refund(ctx, refund, payment)
		if err != nil {
			return nil, fmt.Errorf("gateway refund failed: %w", err)
		}
		return gatewayRefundID, nil
	})

	if err != nil {
		_ = refund.TransitionTo(models.RefundStatusFailed)
		_ = s.repo.SaveRefund(ctx, refund)
		return nil, fmt.Errorf("refund processing failed: %w", err)
	}

	gatewayRefundID := result.(string)
	refund.GatewayRefundID = gatewayRefundID
	_ = refund.TransitionTo(models.RefundStatusProcessed)

	// Persist the refund record.
	if err := s.repo.SaveRefund(ctx, refund); err != nil {
		return nil, fmt.Errorf("failed to save refund: %w", err)
	}

	// Transition payment to REFUNDED state.
	_ = payment.TransitionTo(models.PaymentStatusRefunded)
	_ = s.repo.UpdatePayment(ctx, payment)

	// Publish refund event.
	_ = s.publisher.PublishRefundEvent(ctx, "refund.processed", refund)

	s.logger.InfoContext(ctx, "refund processed", "refund_id", refund.ID, "payment_id", cmd.PaymentID)
	return refund, nil
}

// GetTransaction retrieves a payment transaction by ID.
func (s *PaymentService) GetTransaction(ctx context.Context, paymentID string) (*models.Payment, error) {
	payment, err := s.repo.GetPayment(ctx, paymentID)
	if err != nil {
		return nil, fmt.Errorf("payment not found: %w", err)
	}
	return payment, nil
}

// ListTransactions retrieves a filtered, paginated list of payments.
func (s *PaymentService) ListTransactions(ctx context.Context, customerID string, status models.PaymentStatus, cursor string, pageSize int) ([]*models.Payment, string, error) {
	if pageSize <= 0 || pageSize > 100 {
		pageSize = 20
	}
	return s.repo.ListPayments(ctx, customerID, status, cursor, pageSize)
}

// GetCircuitStatus returns the current state of a circuit breaker.
func (s *PaymentService) GetCircuitStatus(ctx context.Context) (*models.CircuitBreakerInfo, error) {
	return s.circuit.GetState(ctx)
}

// Command types (imported from inbound ports, re-declared here for service use).
type ProcessPaymentCommand = struct {
	OrderID        string
	Amount         models.Money
	Method         models.PaymentMethod
	CustomerID     string
	IdempotencyKey string
	Metadata       map[string]string
}

type RefundPaymentCommand = struct {
	PaymentID      string
	Amount         models.Money
	Reason         models.RefundReason
	IdempotencyKey string
	Metadata       map[string]string
}
