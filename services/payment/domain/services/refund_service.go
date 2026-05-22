// Package services implements the core domain services for the Payment service.
// This file contains the RefundService which orchestrates refund processing
// for previously captured payments. The service validates refund requests,
// checks that the refund amount does not exceed the remaining captured
// balance, submits the refund to the external gateway via the circuit
// breaker, and persists the refund record.
package services

import (
	"context"
	"fmt"
	"log/slog"
<<<<<<< HEAD
	"time"
=======
>>>>>>> origin/release/v0.6.0

	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/ports/outbound"
)

// RefundService implements the refund processing use case for the Payment
// domain. It coordinates refund validation, gateway submission, payment
// state transitions, and event publishing. The service supports both full
// and partial refunds, tracking the remaining captured balance to prevent
// over-refunding.
type RefundService struct {
<<<<<<< HEAD
	gateway outbound.PaymentGatewayPort
	repo    outbound.TransactionRepository
	events  outbound.EventPublisher
	circuit outbound.CircuitBreakerPort
	logger  *slog.Logger
=======
	gateway   outbound.PaymentGatewayPort
	repo      outbound.TransactionRepository
	publisher outbound.EventPublisher
	circuit   outbound.CircuitBreakerPort
	logger    *slog.Logger
>>>>>>> origin/release/v0.6.0
}

// NewRefundService creates a new RefundService with the given outbound
// port implementations.
func NewRefundService(
	gateway outbound.PaymentGatewayPort,
	repo outbound.TransactionRepository,
<<<<<<< HEAD
	events outbound.EventPublisher,
=======
	publisher outbound.EventPublisher,
>>>>>>> origin/release/v0.6.0
	circuit outbound.CircuitBreakerPort,
	logger *slog.Logger,
) *RefundService {
	if logger == nil {
<<<<<<< HEAD
		logger = slog.New(slog.NewTextHandler(nil, nil))
	}
	return &RefundService{
		gateway: gateway,
		repo:    repo,
		events:  events,
		circuit: circuit,
		logger:  logger,
=======
		logger = slog.Default()
	}
	return &RefundService{
		gateway:   gateway,
		repo:      repo,
		publisher: publisher,
		circuit:   circuit,
		logger:    logger,
>>>>>>> origin/release/v0.6.0
	}
}

// RefundPayment initiates a refund for a previously captured payment.
<<<<<<< HEAD
// It performs the following steps in order:
//  1. Validate that the payment exists and is in a refundable state
//  2. Validate that the refund amount does not exceed the payment amount
//  3. Create a refund record
//  4. Submit the refund to the external gateway via the circuit breaker
//  5. Update the payment's refunded amount and status
//  6. Publish a payment refunded event
func (s *RefundService) RefundPayment(ctx context.Context, paymentID string, amount models.Money, reason models.RefundReason, idempotencyKey string) (*models.Refund, error) {
	s.logger.Info("processing refund",
		slog.String("payment_id", paymentID),
	)

	// Step 1: Retrieve the parent payment
	payment, err := s.repo.FindByID(ctx, paymentID)
=======
// It validates the payment is in a refundable state, validates the refund
// amount does not exceed the payment amount, and submits the refund to
// the external gateway via the circuit breaker.
func (s *RefundService) RefundPayment(ctx context.Context, paymentID string, amount models.Money, reason models.RefundReason, idempotencyKey string) (*models.Refund, error) {
	s.logger.InfoContext(ctx, "processing refund",
		slog.String("payment_id", paymentID),
	)

	// Retrieve the parent payment
	payment, err := s.repo.GetPayment(ctx, paymentID)
>>>>>>> origin/release/v0.6.0
	if err != nil {
		return nil, fmt.Errorf("payment %s not found: %w", paymentID, err)
	}

<<<<<<< HEAD
	// Step 2: Validate the payment is in a refundable state
	if payment.Status != models.PaymentStatusCaptured &&
		payment.Status != models.PaymentStatusCompleted {
		return nil, fmt.Errorf("payment in state %s cannot be refunded", payment.Status)
	}

	// Step 3: Validate the refund amount does not exceed the payment amount
=======
	// Validate the payment is in a refundable state
	if payment.Status != models.PaymentStatusCaptured &&
		payment.Status != models.PaymentStatusCompleted &&
		payment.Status != models.PaymentStatusRefunded {
		return nil, fmt.Errorf("payment in state %s cannot be refunded", payment.Status)
	}

	// Validate refund amount does not exceed payment amount
>>>>>>> origin/release/v0.6.0
	if amount.Amount > payment.Amount.Amount {
		return nil, fmt.Errorf("refund amount %d exceeds payment amount %d", amount.Amount, payment.Amount.Amount)
	}

<<<<<<< HEAD
	// Step 4: Create the refund record
=======
	// Create the refund record
>>>>>>> origin/release/v0.6.0
	refund := &models.Refund{
		PaymentID:      paymentID,
		Amount:         amount,
		Reason:         reason,
		Status:         models.RefundStatusPending,
		IdempotencyKey: idempotencyKey,
<<<<<<< HEAD
		CreatedAt:      time.Now().UTC(),
	}

	if err := s.repo.SaveRefund(ctx, refund); err != nil {
		return nil, fmt.Errorf("failed to save refund: %w", err)
	}

	// Step 5: Submit refund to the gateway via circuit breaker
	var gatewayRefundID string
	gatewayErr := s.circuit.Execute(ctx, func(ctx context.Context) error {
		var err error
		gatewayRefundID, err = s.gateway.Refund(ctx, refund, payment)
		return err
	})

	if gatewayErr != nil {
		// Gateway rejected the refund
		_ = refund.TransitionTo(models.RefundStatusFailed)
		_ = s.repo.SaveRefund(ctx, refund)
		return nil, fmt.Errorf("gateway refund failed for refund %s: %w", refund.ID, gatewayErr)
	}

	// Step 6: Update refund with gateway response
	refund.GatewayRefundID = gatewayRefundID
	_ = refund.TransitionTo(models.RefundStatusProcessed)

	if err := s.repo.SaveRefund(ctx, refund); err != nil {
		return nil, fmt.Errorf("failed to save submitted refund: %w", err)
	}

	// Step 7: Apply refund to payment and update status
	_ = payment.TransitionTo(models.PaymentStatusRefunded)
	_ = s.repo.Save(ctx, payment)

	// Step 8: Publish refunded event
	_ = s.events.PublishRefundEvent(ctx, "refund.processed", refund)

	s.logger.Info("refund processed successfully",
		slog.String("refund_id", refund.ID),
		slog.String("payment_id", paymentID),
	)

=======
	}

	// Submit refund to the gateway via circuit breaker
	result, err := s.circuit.Execute(ctx, func() (interface{}, error) {
		gatewayRefundID, err := s.gateway.Refund(ctx, refund, payment)
		if err != nil {
			return nil, fmt.Errorf("gateway refund failed: %w", err)
		}
		return gatewayRefundID, nil
	})

	if err != nil {
		// Circuit open or gateway failed — save as pending
		_ = s.repo.SaveRefund(ctx, refund)
		_ = s.publisher.PublishRefundEvent(ctx, "refund.pending", refund)
		return nil, fmt.Errorf("refund processing failed: %w", err)
	}

	// Refund succeeded — update state
	gatewayRefundID := result.(string)
	refund.GatewayRefundID = gatewayRefundID
	_ = refund.TransitionTo(models.RefundStatusProcessed)

	// Persist the refund
	if err := s.repo.SaveRefund(ctx, refund); err != nil {
		return nil, fmt.Errorf("failed to save refund: %w", err)
	}

	// Update payment status
	_ = payment.TransitionTo(models.PaymentStatusRefunded)
	_ = s.repo.UpdatePayment(ctx, payment)

	// Publish refund event
	_ = s.publisher.PublishRefundEvent(ctx, "refund.processed", refund)

	s.logger.InfoContext(ctx, "refund processed successfully",
		slog.String("refund_id", refund.ID),
		slog.String("payment_id", paymentID),
	)

>>>>>>> origin/release/v0.6.0
	return refund, nil
}
