// Package models defines the core domain entities and value objects for the Payment service.
// These types represent the fundamental business concepts of payment processing, including
// payment records, monetary values with currency, payment methods, and status lifecycle.
// The domain models are pure Go with zero external dependencies, ensuring the hexagonal
// architecture boundary is respected. All monetary amounts use int64 cents to avoid
// floating-point arithmetic errors that are unacceptable in financial systems.
package models

import (
        "time"
)

// PaymentStatus represents the lifecycle state of a payment transaction.
// Payments follow a strict state machine: PENDING → AUTHORIZED → CAPTURED → COMPLETED,
// with possible transitions to FAILED or CANCELLED from any non-terminal state.
// This state machine ensures auditability and prevents invalid state transitions
// that could lead to double-charging or lost payments.
type PaymentStatus string

const (
        PaymentStatusPending    PaymentStatus = "PENDING"
        PaymentStatusAuthorized PaymentStatus = "AUTHORIZED"
        PaymentStatusCaptured   PaymentStatus = "CAPTURED"
        PaymentStatusCompleted  PaymentStatus = "COMPLETED"
        PaymentStatusFailed     PaymentStatus = "FAILED"
        PaymentStatusCancelled  PaymentStatus = "CANCELLED"
        PaymentStatusRefunded   PaymentStatus = "REFUNDED"
)

// PaymentMethod identifies the type of payment instrument used for a transaction.
// Each method has different processing characteristics, risk profiles, and
// settlement timelines that affect the payment lifecycle and reconciliation.
type PaymentMethod string

const (
        PaymentMethodCreditCard PaymentMethod = "CREDIT_CARD"
        PaymentMethodDebitCard  PaymentMethod = "DEBIT_CARD"
        PaymentMethodBankTransfer PaymentMethod = "BANK_TRANSFER"
        PaymentMethodDigitalWallet PaymentMethod = "DIGITAL_WALLET"
        PaymentMethodCrypto      PaymentMethod = "CRYPTO"
)

// Money is a value object representing a monetary amount with currency.
// The amount is stored as int64 cents to eliminate floating-point precision
// issues that are unacceptable in financial calculations. All arithmetic
// operations on Money return new instances, preserving immutability.
// Currency codes follow ISO 4217 (e.g., USD, EUR, GBP, JPY).
type Money struct {
        Amount   int64  `json:"amount"`
        Currency string `json:"currency"`
}

// NewMoney creates a Money value object from a whole-unit amount and currency code.
// The amount parameter represents whole currency units (e.g., dollars), which are
// internally converted to cents. This provides a natural API for callers while
// maintaining cent-based storage internally.
func NewMoney(amount int64, currency string) Money {
        return Money{Amount: amount * 100, Currency: currency}
}

// NewMoneyFromCents creates a Money value object directly from cents.
// This is the preferred constructor when the source data is already in minor units,
// such as when reading from a database or receiving from a payment gateway.
func NewMoneyFromCents(cents int64, currency string) Money {
        return Money{Amount: cents, Currency: currency}
}

// Add returns a new Money value with the other amount added. Both Money values
// must have the same currency; otherwise this operation panics. Immutability is
// preserved by returning a new instance rather than modifying in place.
func (m Money) Add(other Money) Money {
        if m.Currency != other.Currency {
                panic("cannot add money with different currencies")
        }
        return Money{Amount: m.Amount + other.Amount, Currency: m.Currency}
}

// Subtract returns a new Money value with the other amount subtracted.
func (m Money) Subtract(other Money) Money {
        if m.Currency != other.Currency {
                panic("cannot subtract money with different currencies")
        }
        return Money{Amount: m.Amount - other.Amount, Currency: m.Currency}
}

// IsNegative returns true if the monetary amount is below zero.
// Negative amounts are invalid for payments but valid for refunds and adjustments.
func (m Money) IsNegative() bool {
        return m.Amount < 0
}

// IsZero returns true if the monetary amount equals zero.
func (m Money) IsZero() bool {
        return m.Amount == 0
}

// Payment represents a single payment transaction in the system.
// It tracks the full lifecycle from authorization through capture to completion,
// including the relationship to any refunds. Each payment is immutable after
// creation except for status transitions, which follow the defined state machine.
type Payment struct {
        ID            string        `json:"id"`
        OrderID       string        `json:"order_id"`
        Amount        Money         `json:"amount"`
        Method        PaymentMethod `json:"method"`
        Status        PaymentStatus `json:"status"`
        GatewayTxnID  string        `json:"gateway_txn_id,omitempty"`
        CustomerID    string        `json:"customer_id"`
        Metadata      map[string]string `json:"metadata,omitempty"`
        IdempotencyKey string      `json:"idempotency_key,omitempty"`
        CreatedAt     time.Time     `json:"created_at"`
        UpdatedAt     time.Time     `json:"updated_at"`
        CompletedAt   *time.Time    `json:"completed_at,omitempty"`
}

// CanTransitionTo checks whether the payment can transition to the target status.
// This enforces the state machine rules that prevent invalid transitions, such as
// moving from COMPLETED back to PENDING, or from FAILED to CAPTURED.
func (p *Payment) CanTransitionTo(target PaymentStatus) bool {
        transitions := map[PaymentStatus][]PaymentStatus{
                PaymentStatusPending:    {PaymentStatusAuthorized, PaymentStatusFailed, PaymentStatusCancelled},
                PaymentStatusAuthorized: {PaymentStatusCaptured, PaymentStatusFailed, PaymentStatusCancelled},
                PaymentStatusCaptured:   {PaymentStatusCompleted, PaymentStatusRefunded},
                PaymentStatusCompleted:  {PaymentStatusRefunded},
                PaymentStatusFailed:     {},
                PaymentStatusCancelled:  {},
                PaymentStatusRefunded:   {},
        }

        allowed, exists := transitions[p.Status]
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

// TransitionTo attempts to change the payment status to the target value.
// It returns an error if the transition is not allowed by the state machine.
// On success, the UpdatedAt timestamp is refreshed to the current time.
func (p *Payment) TransitionTo(target PaymentStatus) error {
        if !p.CanTransitionTo(target) {
                return ErrInvalidTransition{From: p.Status, To: target}
        }
        p.Status = target
        p.UpdatedAt = time.Now().UTC()
        if target == PaymentStatusCompleted {
                now := time.Now().UTC()
                p.CompletedAt = &now
        }
        return nil
}

// ErrInvalidTransition is returned when a payment status transition violates
// the state machine rules. It includes both the current and target statuses
// to aid in debugging and error reporting.
type ErrInvalidTransition struct {
        From PaymentStatus
        To   PaymentStatus
}

func (e ErrInvalidTransition) Error() string {
        return "invalid payment status transition from " + string(e.From) + " to " + string(e.To)
}
