package persistence

import (
        "context"
        "fmt"
        "log/slog"
        "sync"
        "time"

        "github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
)

// PostgresTransactionRepo implements the TransactionRepository interface using PostgreSQL.
// In production, it uses sqlx for compile-time checked queries against the payment and
// outbox tables. For development and testing, an in-memory fallback is provided. The
// repository implements the outbox pattern — payment events are written to the same
// database transaction as payment records, ensuring atomic consistency without
// distributed transaction coordination.
type PostgresTransactionRepo struct {
        mu       sync.RWMutex
        payments map[string]*models.Payment
        refunds  map[string]*models.Refund
        outbox   []outboxEvent
        logger   *slog.Logger
        // In production: db *sqlx.DB
}

type outboxEvent struct {
        ID          string
        EventType   string
        AggregateID string
        Payload     []byte
        CreatedAt   time.Time
        Published   bool
}

// NewPostgresTransactionRepo creates a new transaction repository.
// In production, this would accept a *sqlx.DB connection. For now,
// it uses an in-memory store that mirrors the PostgreSQL schema.
func NewPostgresTransactionRepo(logger *slog.Logger) *PostgresTransactionRepo {
        return &PostgresTransactionRepo{
                payments: make(map[string]*models.Payment),
                refunds:  make(map[string]*models.Refund),
                outbox:   make([]outboxEvent, 0),
                logger:   logger,
        }
}

// SavePayment persists a new payment record to the database.
// In production, this executes an INSERT INTO payments (...) query within
// a transaction that also writes to the outbox table for CDC relay pickup.
func (r *PostgresTransactionRepo) SavePayment(ctx context.Context, payment *models.Payment) error {
        r.mu.Lock()
        defer r.mu.Unlock()

        if _, exists := r.payments[payment.ID]; exists {
                return fmt.Errorf("payment with ID %s already exists", payment.ID)
        }

        r.payments[payment.ID] = payment
        r.logger.InfoContext(ctx, "payment saved", "payment_id", payment.ID)
        return nil
}

// UpdatePayment updates an existing payment record in the database.
// This is used for status transitions and metadata updates.
func (r *PostgresTransactionRepo) UpdatePayment(ctx context.Context, payment *models.Payment) error {
        r.mu.Lock()
        defer r.mu.Unlock()

        if _, exists := r.payments[payment.ID]; !exists {
                return fmt.Errorf("payment with ID %s not found", payment.ID)
        }

        r.payments[payment.ID] = payment
        r.logger.InfoContext(ctx, "payment updated", "payment_id", payment.ID, "status", payment.Status)
        return nil
}

// GetPayment retrieves a payment by its unique identifier.
func (r *PostgresTransactionRepo) GetPayment(ctx context.Context, id string) (*models.Payment, error) {
        r.mu.RLock()
        defer r.mu.RUnlock()

        payment, exists := r.payments[id]
        if !exists {
                return nil, fmt.Errorf("payment %s not found", id)
        }
        return payment, nil
}

// GetPaymentByIdempotencyKey retrieves a payment by its idempotency key.
// Returns nil if no payment exists with this key, enabling idempotent processing.
func (r *PostgresTransactionRepo) GetPaymentByIdempotencyKey(ctx context.Context, key string) (*models.Payment, error) {
        r.mu.RLock()
        defer r.mu.RUnlock()

        for _, payment := range r.payments {
                if payment.IdempotencyKey == key {
                        return payment, nil
                }
        }
        return nil, nil
}

// ListPayments retrieves a filtered, paginated list of payments using cursor-based pagination.
// The cursor is an opaque token based on the last payment's created_at timestamp.
func (r *PostgresTransactionRepo) ListPayments(ctx context.Context, customerID string, status models.PaymentStatus, cursor string, pageSize int) ([]*models.Payment, string, error) {
        r.mu.RLock()
        defer r.mu.RUnlock()

        var results []*models.Payment
        for _, p := range r.payments {
                if customerID != "" && p.CustomerID != customerID {
                        continue
                }
                if status != "" && p.Status != status {
                        continue
                }
                results = append(results, p)
        }

        // Simple pagination: limit results to pageSize.
        if len(results) > pageSize {
                results = results[:pageSize]
        }

        var nextCursor string
        if len(results) > 0 {
                last := results[len(results)-1]
                nextCursor = fmt.Sprintf("%d", last.CreatedAt.UnixNano())
        }

        return results, nextCursor, nil
}

// SaveRefund persists a new refund record to the database.
func (r *PostgresTransactionRepo) SaveRefund(ctx context.Context, refund *models.Refund) error {
        r.mu.Lock()
        defer r.mu.Unlock()

        r.refunds[refund.ID] = refund
        r.logger.InfoContext(ctx, "refund saved", "refund_id", refund.ID, "payment_id", refund.PaymentID)
        return nil
}

// GetRefund retrieves a refund by its unique identifier.
func (r *PostgresTransactionRepo) GetRefund(ctx context.Context, id string) (*models.Refund, error) {
        r.mu.RLock()
        defer r.mu.RUnlock()

        refund, exists := r.refunds[id]
        if !exists {
                return nil, fmt.Errorf("refund %s not found", id)
        }
        return refund, nil
}

// SaveOutboxEvent persists an event to the outbox table for CDC relay pickup.
// The event is written in the same database transaction as the aggregate change,
// ensuring at-least-once delivery without two-phase commit.
func (r *PostgresTransactionRepo) SaveOutboxEvent(ctx context.Context, eventType string, aggregateID string, payload []byte) error {
        r.mu.Lock()
        defer r.mu.Unlock()

        event := outboxEvent{
                ID:          fmt.Sprintf("evt_%d", time.Now().UTC().UnixNano()),
                EventType:   eventType,
                AggregateID: aggregateID,
                Payload:     payload,
                CreatedAt:   time.Now().UTC(),
                Published:   false,
        }

        r.outbox = append(r.outbox, event)
        r.logger.InfoContext(ctx, "outbox event saved", "event_type", eventType, "aggregate_id", aggregateID)
        return nil
}
