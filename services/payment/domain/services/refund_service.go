// Package services implements the core domain services for the Payment service.
// This file contains the RefundService which orchestrates refund processing
// for previously captured payments. The service validates refund requests,
// checks that the refund amount does not exceed the remaining captured
// balance, submits the refund to the external gateway via the circuit
// breaker, and persists the refund record. If the gateway is unavailable,
// the refund is recorded in a pending state for automatic retry when
// connectivity is restored, ensuring that refunds are never lost.
package services

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/gstack/payment-service/domain/models"
	"github.com/gstack/payment-service/domain/ports/outbound"
)

// RefundService implements the refund processing use case for the Payment
// domain. It coordinates refund validation, gateway submission, payment
// state transitions, and event publishing. The service supports both full
// and partial refunds, tracking the remaining captured balance to prevent
// over-refunding. Multiple partial refunds are allowed up to the total
// captured amount, and each refund is assigned a unique ID for tracking.
type RefundService struct {
	gateway outbound.PaymentGatewayPort
	repo    outbound.TransactionRepository
	events  outbound.EventPublisherPort
	circuit outbound.CircuitBreakerPort
	logger  *slog.Logger
}

// NewRefundService creates a new RefundService with the given outbound
// port implementations. The logger may be nil -- a default discard
// logger is used in that case.
func NewRefundService(
	gateway outbound.PaymentGatewayPort,
	repo outbound.TransactionRepository,
	events outbound.EventPublisherPort,
	circuit outbound.CircuitBreakerPort,
	logger *slog.Logger,
) *RefundService {
	if logger == nil {
		logger = slog.New(slog.NewTextHandler(nil, nil))
	}
	return &RefundService{
		gateway: gateway,
		repo:    repo,
		events:  events,
		circuit: circuit,
		logger:  logger,
	}
}

// RefundPayment initiates a refund for a previously captured payment.
// It performs the following steps in order:
//  1. Validate that the payment exists and is in a refundable state
//  2. Validate that the refund amount does not exceed the remaining captured balance
//  3. Create a refund record
//  4. Submit the refund to the external gateway via the circuit breaker
//  5. Update the payment's refunded amount and status
//  6. Publish a payment refunded event
//
// If the gateway is unavailable (circuit breaker open), the refund is
// recorded in Pending state and will be submitted when the circuit
// breaker allows traffic again.
func (s *RefundService) RefundPayment(ctx context.Context, req models.RefundPaymentRequest) (models.RefundPaymentResponse, error) {
	s.logger.Info("processing refund",
		slog.String("payment_id", req.PaymentID),
		slog.String("reference_id", req.ReferenceID),
		slog.String("reason", req.Reason.String()),
	)

	// Step 1: Retrieve the parent payment
	payment, err := s.repo.FindByID(ctx, req.PaymentID)
	if err != nil {
		return models.RefundPaymentResponse{}, fmt.Errorf("payment %s not found: %w", req.PaymentID, err)
	}

	// Step 2: Validate the payment is in a refundable state
	if payment.Status != models.PaymentStatusCaptured &&
		payment.Status != models.PaymentStatusPartiallyRefunded {
		return models.RefundPaymentResponse{}, &models.PaymentNotCapturedError{
			PaymentID: req.PaymentID,
			Status:    payment.Status,
		}
	}

	// Step 3: Validate the refund amount
	remaining, err := payment.RemainingCapturedBalance()
	if err != nil {
		return models.RefundPaymentResponse{}, fmt.Errorf("failed to compute remaining balance: %w", err)
	}

	gte, err := remaining.GreaterThanOrEqual(req.Amount)
	if err != nil {
		return models.RefundPaymentResponse{}, fmt.Errorf("currency mismatch in refund amount: %w", err)
	}
	if !gte {
		return models.RefundPaymentResponse{}, &models.RefundExceedsCapturedError{
			PaymentID:        req.PaymentID,
			RequestedAmount:  req.Amount,
			RemainingBalance: remaining,
		}
	}

	// Step 4: Validate the refund amount is positive
	if !req.Amount.IsPositive() {
		return models.RefundPaymentResponse{}, &models.AmountValidationError{
			PaymentID: req.PaymentID,
			Reason:    "refund amount must be positive",
		}
	}

	// Step 5: Create the refund record
	refund := &models.Refund{
		PaymentID:   req.PaymentID,
		OrderID:     payment.OrderID,
		Amount:      req.Amount,
		Reason:      req.Reason,
		ReferenceID: req.ReferenceID,
		InitiatedBy: req.InitiatedBy,
		Status:      models.RefundStatusPending,
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
	}

	if err := s.repo.SaveRefund(ctx, refund); err != nil {
		return models.RefundPaymentResponse{}, fmt.Errorf("failed to save refund: %w", err)
	}

	// Step 6: Submit refund to the gateway via circuit breaker
	var refundResp outbound.GatewayRefundResponse
	gatewayErr := s.circuit.Execute(ctx, func(ctx context.Context) error {
		var err error
		refundResp, err = s.gateway.Refund(ctx, outbound.GatewayRefundRequest{
			RefundID:         refund.ID,
			PaymentID:        payment.ID,
			GatewayReference: payment.GatewayReference,
			Amount:           req.Amount,
			IdempotencyKey:   req.ReferenceID,
		})
		return err
	})

	if gatewayErr != nil {
		if _, ok := gatewayErr.(*models.GatewayUnavailableError); ok {
			// Gateway unavailable -- refund stays in Pending for retry
			s.logger.Warn("gateway unavailable during refund, refund saved as pending",
				slog.String("refund_id", refund.ID),
				slog.String("payment_id", req.PaymentID),
			)
			return models.RefundPaymentResponse{
				RefundID:          refund.ID,
				PaymentID:         req.PaymentID,
				RefundAmount:      req.Amount,
				RemainingCaptured: remaining,
				Status:            models.RefundStatusPending,
			}, nil
		}

		// Gateway rejected the refund
		if markErr := refund.MarkFailed(); markErr != nil {
			s.logger.Error("failed to mark refund as failed",
				slog.String("refund_id", refund.ID),
			)
		}
		_ = s.repo.SaveRefund(ctx, refund)
		return models.RefundPaymentResponse{}, fmt.Errorf("gateway refund failed for refund %s: %w", refund.ID, gatewayErr)
	}

	// Step 7: Update refund with gateway response
	estimatedSettlement := time.Now().Add(5 * 24 * time.Hour) // Default 5 business days
	if err := refund.Submit(refundResp.GatewayReference, estimatedSettlement); err != nil {
		return models.RefundPaymentResponse{}, fmt.Errorf("failed to update refund status: %w", err)
	}

	if err := s.repo.SaveRefund(ctx, refund); err != nil {
		return models.RefundPaymentResponse{}, fmt.Errorf("failed to save submitted refund: %w", err)
	}

	// Step 8: Apply refund to payment and update status
	if err := payment.ApplyRefund(req.Amount); err != nil {
		return models.RefundPaymentResponse{}, fmt.Errorf("failed to apply refund to payment: %w", err)
	}

	if err := s.repo.Save(ctx, payment); err != nil {
		return models.RefundPaymentResponse{}, fmt.Errorf("failed to save payment after refund: %w", err)
	}

	// Step 9: Publish refunded event
	_ = s.publishRefundEvent(ctx, "com.company.payment.refunded", refund.ID, payment.OrderID, refund)

	// Compute new remaining balance
	newRemaining, _ := payment.RemainingCapturedBalance()

	s.logger.Info("refund processed successfully",
		slog.String("refund_id", refund.ID),
		slog.String("payment_id", req.PaymentID),
		slog.String("payment_status", payment.Status.String()),
	)

	return models.RefundPaymentResponse{
		RefundID:          refund.ID,
		PaymentID:         req.PaymentID,
		RefundAmount:      req.Amount,
		RemainingCaptured: newRemaining,
		Status:            refund.Status,
	}, nil
}

// publishRefundEvent is a helper that publishes a refund domain event.
func (s *RefundService) publishRefundEvent(ctx context.Context, eventType, aggregateID, correlationID string, data interface{}) error {
	err := s.events.Publish(ctx, outbound.DomainEvent{
		Type:          eventType,
		AggregateID:   aggregateID,
		CorrelationID: correlationID,
		ContentType:   "application/json",
	})
	if err != nil {
		s.logger.Error("failed to publish refund event",
			slog.String("event_type", eventType),
			slog.String("aggregate_id", aggregateID),
			slog.String("error", err.Error()),
		)
	}
	return err
}
