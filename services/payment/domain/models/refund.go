package models

import (
	"time"
)

// RefundStatus represents the lifecycle state of a refund transaction.
// Refunds follow a simpler state machine than payments since they are
// always tied to an existing completed payment. The typical flow is
// PENDING → PROCESSED, with a possible transition to FAILED if the
// gateway rejects the refund request.
type RefundStatus string

const (
	RefundStatusPending   RefundStatus = "PENDING"
	RefundStatusProcessed RefundStatus = "PROCESSED"
	RefundStatusFailed    RefundStatus = "FAILED"
)

// RefundReason categorizes why a refund was initiated. This classification
// supports analytics, chargeback prevention, and customer satisfaction tracking.
// Each reason may trigger different processing rules and notification patterns.
type RefundReason string

const (
	RefundReasonCustomerRequest RefundReason = "CUSTOMER_REQUEST"
	RefundReasonProductDefect   RefundReason = "PRODUCT_DEFECT"
	RefundReasonFraud           RefundReason = "FRAUD"
	RefundReasonDuplicate       RefundReason = "DUPLICATE"
	RefundReasonAdminDecision   RefundReason = "ADMIN_DECISION"
)

// Refund represents a refund transaction against a previously completed payment.
// Refunds can be partial (less than the original payment amount) or full.
// Each refund is idempotent based on its IdempotencyKey, preventing duplicate
// refund processing that could result in over-refunding the customer.
type Refund struct {
	ID              string            `json:"id"`
	PaymentID       string            `json:"payment_id"`
	Amount          Money             `json:"amount"`
	Reason          RefundReason      `json:"reason"`
	Status          RefundStatus      `json:"status"`
	GatewayRefundID string            `json:"gateway_refund_id,omitempty"`
	IdempotencyKey  string            `json:"idempotency_key,omitempty"`
	Metadata        map[string]string `json:"metadata,omitempty"`
	CreatedAt       time.Time         `json:"created_at"`
	ProcessedAt     *time.Time        `json:"processed_at,omitempty"`
}

// IsPartial checks whether this refund covers less than the full payment amount.
// Partial refunds are common in scenarios like partial order cancellations or
// goodwill adjustments. The comparison requires the original payment amount
// to determine the refund ratio.
func (r *Refund) IsPartial(originalAmount Money) bool {
	if r.Amount.Currency != originalAmount.Currency {
		return true // Different currency implies partial in practical terms
	}
	return r.Amount.Amount < originalAmount.Amount
}

// CanTransitionTo validates refund status transitions.
// Refunds have a simpler state machine than payments since they cannot be
// cancelled once initiated — they either succeed or fail at the gateway.
func (r *Refund) CanTransitionTo(target RefundStatus) bool {
	transitions := map[RefundStatus][]RefundStatus{
		RefundStatusPending:   {RefundStatusProcessed, RefundStatusFailed},
		RefundStatusProcessed: {},
		RefundStatusFailed:    {},
	}

	allowed, exists := transitions[r.Status]
	if !exists {
		return false
	}
	for _, s := range allowed {
		if s == target {
			return true
		}
	}
	return false
}

// TransitionTo attempts to change the refund status and returns an error
// if the transition is not allowed. On successful transition to PROCESSED,
// the ProcessedAt timestamp is set to the current time.
func (r *Refund) TransitionTo(target RefundStatus) error {
	if !r.CanTransitionTo(target) {
		return ErrInvalidRefundTransition{From: r.Status, To: target}
	}
	r.Status = target
	if target == RefundStatusProcessed {
		now := time.Now().UTC()
		r.ProcessedAt = &now
	}
	return nil
}

// ErrInvalidRefundTransition is returned when a refund status transition
// violates the state machine rules.
type ErrInvalidRefundTransition struct {
	From RefundStatus
	To   RefundStatus
}

func (e ErrInvalidRefundTransition) Error() string {
	return "invalid refund status transition from " + string(e.From) + " to " + string(e.To)
}
