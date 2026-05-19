// Package outbound defines the driven port interfaces for the Payment domain.
// This file provides the EventPublisher interface for publishing domain
// events to the event backbone using the transactional outbox pattern.
// Events are written to a PostgreSQL outbox table in the same transaction
// as the payment state change, guaranteeing consistency between the
// database state and the event stream.
package outbound

import (
	"context"
	"time"
)

// DomainEvent represents a payment domain event that is published to
// the event backbone. Events follow the CloudEvents specification with
// a type prefix of "com.company.payment." and include a correlation ID
// that links them to the originating order event for end-to-end
// traceability.
type DomainEvent struct {
	ID          string            // Unique event identifier (UUID v4)
	Source      string            // Event source (e.g., "payment-service")
	Type        string            // CloudEvents type (e.g., "com.company.payment.authorized")
	Time        time.Time         // Event timestamp
	AggregateID string            // Payment or refund ID that this event relates to
	CorrelationID string          // Links to the originating order event
	Data        []byte            // Event payload (serialized protobuf or JSON)
	ContentType string            // Payload content type (e.g., "application/protobuf")
	Metadata    map[string]string // Additional event metadata
}

// EventPublisherPort defines the interface for publishing payment domain
// events. Events are published using the transactional outbox pattern:
// the event is first written to a PostgreSQL outbox table in the same
// transaction as the payment state change, then a relay process publishes
// it to Kafka. This guarantees that the payment database state and the
// event stream are always consistent. Payment events are among the most
// critical in the system because they drive downstream financial reporting,
// order state transitions, and customer notifications.
type EventPublisherPort interface {
	// Publish publishes a single domain event to the event backbone.
	// In the outbox pattern, this writes the event to the outbox table
	// rather than directly to Kafka. The relay process handles actual
	// publication asynchronously.
	Publish(ctx context.Context, event DomainEvent) error

	// PublishBatch publishes multiple events atomically. All events
	// are written to the outbox in a single transaction, ensuring
	// that either all or none of the events are persisted.
	PublishBatch(ctx context.Context, events []DomainEvent) error
}
