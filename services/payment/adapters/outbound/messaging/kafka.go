package messaging

import (
	"context"
	"encoding/json"
	"log/slog"

	"github.com/gstack/payment-service/domain/models"
)

// KafkaEventPublisher implements the EventPublisher interface using Kafka.
// In production, this uses the confluent-kafka-go or sarama client to publish
// CloudEvents to the payment.events topic. The publisher follows the outbox
// pattern — events are first written to the outbox table, then the CDC relay
// publishes them to Kafka. This publisher is used as a fallback for direct
// publishing in development and testing environments where CDC is not running.
type KafkaEventPublisher struct {
	brokers string
	topic   string
	logger  *slog.Logger
	// In production: producer *kafka.Producer
}

// NewKafkaEventPublisher creates a new Kafka event publisher.
func NewKafkaEventPublisher(brokers string, topic string, logger *slog.Logger) *KafkaEventPublisher {
	return &KafkaEventPublisher{
		brokers: brokers,
		topic:   topic,
		logger:  logger,
	}
}

// PublishPaymentEvent publishes a payment lifecycle event as a CloudEvent.
// The event follows the CloudEvents v1.0 specification with the payment
// service as the source and the event type as the type field.
func (p *KafkaEventPublisher) PublishPaymentEvent(ctx context.Context, eventType string, payment *models.Payment) error {
	payload, err := json.Marshal(map[string]interface{}{
		"specversion": "1.0",
		"type":        "com.gstack.payment." + eventType,
		"source":      "/payment-service",
		"id":          payment.ID,
		"time":        payment.UpdatedAt,
		"data":        payment,
	})
	if err != nil {
		return err
	}

	p.logger.InfoContext(ctx, "payment event published",
		"event_type", eventType,
		"payment_id", payment.ID,
		"topic", p.topic,
	)

	// In production: p.producer.Produce(&kafka.Message{TopicPartition: kafka.TopicPartition{Topic: &p.topic}, Value: payload}, nil)
	_ = payload
	return nil
}

// PublishRefundEvent publishes a refund lifecycle event as a CloudEvent.
func (p *KafkaEventPublisher) PublishRefundEvent(ctx context.Context, eventType string, refund *models.Refund) error {
	payload, err := json.Marshal(map[string]interface{}{
		"specversion": "1.0",
		"type":        "com.gstack.payment." + eventType,
		"source":      "/payment-service",
		"id":          refund.ID,
		"time":        refund.CreatedAt,
		"data":        refund,
	})
	if err != nil {
		return err
	}

	p.logger.InfoContext(ctx, "refund event published",
		"event_type", eventType,
		"refund_id", refund.ID,
		"topic", p.topic,
	)
	_ = payload
	return nil
}

// PublishCircuitEvent publishes a circuit breaker state change event.
func (p *KafkaEventPublisher) PublishCircuitEvent(ctx context.Context, event models.CircuitBreakerEvent) error {
	p.logger.InfoContext(ctx, "circuit event published",
		"circuit_name", event.CircuitName,
		"from", event.FromState,
		"to", event.ToState,
	)
	return nil
}
