package observability

import (
	"context"
	"log/slog"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
)

// OtelAdapter provides OpenTelemetry instrumentation for the Payment service.
// It creates spans for each payment operation, records metrics (payment count,
// latency histograms, circuit breaker state gauges), and logs structured events.
// All telemetry follows the OTel semantic conventions for payment systems.
type OtelAdapter struct {
	logger *slog.Logger
	// In production: tracer trace.Tracer, meter metric.Meter
}

// NewOtelAdapter creates a new OTel instrumentation adapter.
func NewOtelAdapter(logger *slog.Logger) *OtelAdapter {
	return &OtelAdapter{logger: logger}
}

// StartSpan creates a new OTel span for a payment operation.
// The span name follows the pattern "payment.{operation}" and includes
// the payment ID and order ID as attributes for trace correlation.
func (o *OtelAdapter) StartSpan(ctx context.Context, operation string, attrs map[string]string) (context.Context, func()) {
	start := time.Now().UTC()
	o.logger.InfoContext(ctx, "span started", "operation", operation, "attrs", attrs)

	end := func() {
		duration := time.Since(start)
		o.logger.InfoContext(ctx, "span ended",
			"operation", operation,
			"duration_ms", duration.Milliseconds(),
		)
		// In production: span.End(), record duration to histogram
	}

	return ctx, end
}

// RecordPaymentMetric records metrics for a payment operation.
// This includes the payment amount, method, status, and latency.
func (o *OtelAdapter) RecordPaymentMetric(ctx context.Context, payment *models.Payment, duration time.Duration) {
	o.logger.InfoContext(ctx, "payment metric recorded",
		"payment_id", payment.ID,
		"status", string(payment.Status),
		"method", string(payment.Method),
		"amount_cents", payment.Amount.Amount,
		"currency", payment.Amount.Currency,
		"duration_ms", duration.Milliseconds(),
	)
	// In production: paymentCounter.Add(ctx, 1, ...), latencyHistogram.Record(ctx, duration, ...)
}

// RecordCircuitBreakerState records the current circuit breaker state as a gauge metric.
func (o *OtelAdapter) RecordCircuitBreakerState(ctx context.Context, info *models.CircuitBreakerInfo) {
	o.logger.InfoContext(ctx, "circuit breaker state",
		"circuit", info.Name,
		"state", string(info.State),
		"failures", info.FailureCount,
		"successes", info.SuccessCount,
	)
	// In production: circuitGauge.Record(ctx, ...)
}
