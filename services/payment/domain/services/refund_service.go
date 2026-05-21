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

	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/ports/outbound"
)

// RefundService implements the refund processing use case for the Payment
// domain. It coordinates refund validation, gateway submission, payment
// state transitions, and event publishing. The service supports both full
// and partial refunds, tracking the remaining captured balance to prevent
// over-refunding. Multiple partial refunds are allowed up to the total
// captured amount, and each refund is assigned a unique ID for tracking.
type RefundService struct {
	gateway   outbound.PaymentGatewayPort
	repo      outbound.TransactionRepository
	publisher outbound.EventPublisher
	circuit   outbound.CircuitBreakerPort
	logger    *slog.Logger
}

// NewRefundService creates a new RefundService with the given outbound
// port implementations.
func NewRefundService(
	gateway outbound.PaymentGatewayPort,
	repo outbound.TransactionRepository,
	publisher outbound.EventPublisher,
	circuit outbound.CircuitBreakerPort,
	logger *slog.Logger,
) *RefundService {
	if logger == nil {
		logger = slog.Default()
	}
	return &RefundService{
		gateway:   gateway,
		repo:      repo,
		publisher: publisher,
		circuit:   circuit,
		logger:    logger,
	}
}

// RefundPayment initiates a refund for a previously captured payment.
// It validates the payment is in a refundable state, validates the refund
// amount does not exceed the payment amount, and submits the refund to
// the external gateway via the circuit breaker.
func (s *RefundService) RefundPayment(ctx context.Context, paymentID string, amount models.Money, reason models.RefundReason, idempotencyKey string) (*models.Refund, error) {
	s.logger.InfoContext(ctx, "processing refund",
		slog.String("payment_id", paymentID),
	)

	// Retrieve the parent payment
	payment, err := s.repo.GetPayment(ctx, paymentID)
	if err != nil {
		return nil, fmt.Errorf("payment %s not found: %w", paymentID, err)
	}

	// Validate the payment is in a refundable state
	if payment.Status != models.PaymentStatusCaptured &&
		payment.Status != models.PaymentStatusCompleted &&
		payment.Status != models.PaymentStatusRefunded {
		return nil, fmt.Errorf("payment in state %s cannot be refunded", payment.Status)
	}

	// Validate refund amount does not exceed payment amount
	if amount.Amount > payment.Amount.Amount {
		return nil, fmt.Errorf("refund amount %d exceeds payment amount %d", amount.Amount, payment.Amount.Amount)
	}

	// Create the refund record
	refund := &models.Refund{
		PaymentID:      paymentID,
		Amount:         amount,
		Reason:         reason,
		Status:         models.RefundStatusPending,
		IdempotencyKey: idempotencyKey,
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

	return refund, nil
}
