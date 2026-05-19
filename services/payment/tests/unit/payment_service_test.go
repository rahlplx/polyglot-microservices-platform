package unit

import (
	"context"
	"testing"

	"github.com/gstack/payment-service/domain/models"
)

// TestMoneyAdd verifies that adding two Money values with the same currency
// produces the correct sum. This is a fundamental operation for any financial
// system and must be correct to the cent.
func TestMoneyAdd(t *testing.T) {
	a := models.NewMoneyFromCents(1000, "USD") // $10.00
	b := models.NewMoneyFromCents(500, "USD")  // $5.00

	result := a.Add(b)

	if result.Amount != 1500 {
		t.Errorf("expected 1500 cents, got %d", result.Amount)
	}
	if result.Currency != "USD" {
		t.Errorf("expected USD currency, got %s", result.Currency)
	}
}

// TestMoneySubtract verifies that subtracting Money values produces the
// correct difference. This operation is used for refund calculations.
func TestMoneySubtract(t *testing.T) {
	a := models.NewMoneyFromCents(1000, "USD")
	b := models.NewMoneyFromCents(300, "USD")

	result := a.Subtract(b)

	if result.Amount != 700 {
		t.Errorf("expected 700 cents, got %d", result.Amount)
	}
}

// TestMoneyDifferentCurrencyPanics verifies that adding Money values
// with different currencies causes a panic. Cross-currency operations
// require explicit conversion and should never happen implicitly.
func TestMoneyDifferentCurrencyPanics(t *testing.T) {
	defer func() {
		if r := recover(); r == nil {
			t.Error("expected panic when adding different currencies")
		}
	}()

	a := models.NewMoneyFromCents(1000, "USD")
	b := models.NewMoneyFromCents(500, "EUR")
	a.Add(b)
}

// TestPaymentStatusTransition verifies the payment state machine rules.
// A PENDING payment can transition to AUTHORIZED or FAILED, but not
// directly to COMPLETED or REFUNDED.
func TestPaymentStatusTransition(t *testing.T) {
	payment := &models.Payment{
		ID:     "pay_test1",
		Status: models.PaymentStatusPending,
		Amount: models.NewMoneyFromCents(5000, "USD"),
	}

	// Valid transition: PENDING → AUTHORIZED
	if err := payment.TransitionTo(models.PaymentStatusAuthorized); err != nil {
		t.Errorf("expected valid transition PENDING → AUTHORIZED, got error: %v", err)
	}

	// Invalid transition: AUTHORIZED → PENDING
	if err := payment.TransitionTo(models.PaymentStatusPending); err == nil {
		t.Error("expected invalid transition AUTHORIZED → PENDING to fail")
	}

	// Valid transition: AUTHORIZED → CAPTURED
	if err := payment.TransitionTo(models.PaymentStatusCaptured); err != nil {
		t.Errorf("expected valid transition AUTHORIZED → CAPTURED, got error: %v", err)
	}
}

// TestPaymentInvalidTransition verifies that invalid state transitions
// return an error of type ErrInvalidTransition.
func TestPaymentInvalidTransition(t *testing.T) {
	payment := &models.Payment{
		ID:     "pay_test2",
		Status: models.PaymentStatusFailed,
		Amount: models.NewMoneyFromCents(5000, "USD"),
	}

	err := payment.TransitionTo(models.PaymentStatusAuthorized)
	if err == nil {
		t.Error("expected error for FAILED → AUTHORIZED transition")
	}

	_, ok := err.(models.ErrInvalidTransition)
	if !ok {
		t.Errorf("expected ErrInvalidTransition, got %T", err)
	}
}

// TestRefundPartial verifies that partial refund detection works correctly.
// A refund for less than the original payment amount is considered partial.
func TestRefundPartial(t *testing.T) {
	originalAmount := models.NewMoneyFromCents(10000, "USD") // $100.00
	refundAmount := models.NewMoneyFromCents(5000, "USD")   // $50.00

	refund := &models.Refund{
		ID:       "ref_test1",
		PaymentID: "pay_test1",
		Amount:   refundAmount,
		Status:   models.RefundStatusPending,
	}

	if !refund.IsPartial(originalAmount) {
		t.Error("expected refund to be partial")
	}
}

// TestRefundFull verifies that a full refund is not detected as partial.
func TestRefundFull(t *testing.T) {
	originalAmount := models.NewMoneyFromCents(10000, "USD")
	refundAmount := models.NewMoneyFromCents(10000, "USD")

	refund := &models.Refund{
		ID:       "ref_test2",
		PaymentID: "pay_test2",
		Amount:   refundAmount,
		Status:   models.RefundStatusPending,
	}

	if refund.IsPartial(originalAmount) {
		t.Error("expected full refund to not be partial")
	}
}
