// Package observability implements the outbound OpenTelemetry instrumentation adapter.
// It provides tracing, metrics, and logging instrumentation for all Gateway operations.
package observability

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/propagation"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.24.0"
	"go.opentelemetry.io/otel/trace"
)

// OTelConfig holds the configuration for the OpenTelemetry adapter.
type OTelConfig struct {
	ServiceName    string        // Service name for resource attributes
	ServiceVersion string        // Service version for resource attributes
	OTLPEndpoint   string        // OTel Collector endpoint (host:port)
	TraceEnabled   bool          // Whether tracing is enabled
	MetricsEnabled bool          // Whether metrics are enabled
	SampleRate     float64       // Trace sampling rate (0.0 - 1.0)
	ExportInterval time.Duration // Metric export interval
	ExportTimeout  time.Duration // Metric export timeout
}

// OTelInstrumentation provides OpenTelemetry instrumentation for the Gateway.
// It wraps the OTel SDK to provide a simpler interface for creating spans,
// recording metrics, and propagating trace context.
type OTelInstrumentation struct {
	config  OTelConfig
	logger  *slog.Logger

	tracerProvider *sdktrace.TracerProvider
	meterProvider  *sdkmetric.MeterProvider
	tracer         trace.Tracer
	meter          metric.Meter

	// Metrics counters and histograms
	requestCounter    metric.Int64Counter
	requestDuration   metric.Float64Histogram
	rateLimitCounter  metric.Int64Counter
	activeConnections metric.Int64UpDownCounter
	upstreamLatency   metric.Float64Histogram
}

// NewOTelInstrumentation creates and initializes a new OTel instrumentation adapter.
func NewOTelInstrumentation(config OTelConfig, logger *slog.Logger) (*OTelInstrumentation, error) {
	if logger == nil {
		logger = slog.Default()
	}

	inst := &OTelInstrumentation{
		config: config,
		logger: logger,
	}

	ctx := context.Background()

	// Create resource with service attributes
	res, err := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceNameKey.String(config.ServiceName),
			semconv.ServiceVersionKey.String(config.ServiceVersion),
			attribute.String("service.namespace", "gateway"),
			attribute.String("deployment.environment", "production"),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create OTel resource: %w", err)
	}

	// Initialize tracing
	if config.TraceEnabled {
		if err := inst.initTracing(ctx, res); err != nil {
			return nil, fmt.Errorf("failed to initialize tracing: %w", err)
		}
	}

	// Initialize metrics
	if config.MetricsEnabled {
		if err := inst.initMetrics(ctx, res); err != nil {
			return nil, fmt.Errorf("failed to initialize metrics: %w", err)
		}
	}

	// Set global propagator for W3C Trace Context
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	return inst, nil
}

// initTracing initializes the trace provider and exporter.
func (inst *OTelInstrumentation) initTracing(ctx context.Context, res *resource.Resource) error {
	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint(inst.config.OTLPEndpoint),
		otlptracegrpc.WithInsecure(),
	)
	if err != nil {
		return fmt.Errorf("failed to create trace exporter: %w", err)
	}

	// Configure sampling
	sampler := sdktrace.ParentBased(
		sdktrace.TraceIDRatioBased(inst.config.SampleRate),
	)

	inst.tracerProvider = sdktrace.NewTracerProvider(
		sdktrace.WithResource(res),
		sdktrace.WithBatcher(exporter),
		sdktrace.WithSampler(sampler),
	)

	otel.SetTracerProvider(inst.tracerProvider)
	inst.tracer = inst.tracerProvider.Tracer(
		"github.com/comprehensive-architecture/services/gateway",
		trace.WithInstrumentationVersion(inst.config.ServiceVersion),
	)

	inst.logger.Info("OTel tracing initialized",
		slog.String("endpoint", inst.config.OTLPEndpoint),
		slog.Float64("sample_rate", inst.config.SampleRate),
	)
	return nil
}

// initMetrics initializes the meter provider and registers Gateway metrics.
func (inst *OTelInstrumentation) initMetrics(ctx context.Context, res *resource.Resource) error {
	exporter, err := otlpmetricgrpc.New(ctx,
		otlpmetricgrpc.WithEndpoint(inst.config.OTLPEndpoint),
		otlpmetricgrpc.WithInsecure(),
	)
	if err != nil {
		return fmt.Errorf("failed to create metric exporter: %w", err)
	}

	inst.meterProvider = sdkmetric.NewMeterProvider(
		sdkmetric.WithResource(res),
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(exporter,
			sdkmetric.WithInterval(inst.config.ExportInterval),
			sdkmetric.WithTimeout(inst.config.ExportTimeout),
		)),
	)

	otel.SetMeterProvider(inst.meterProvider)
	inst.meter = inst.meterProvider.Meter(
		"github.com/comprehensive-architecture/services/gateway",
		metric.WithInstrumentationVersion(inst.config.ServiceVersion),
	)

	// Register Gateway-specific metrics
	inst.requestCounter, err = inst.meter.Int64Counter(
		"gateway.requests.total",
		metric.WithDescription("Total number of requests processed by the gateway"),
		metric.WithUnit("{request}"),
	)
	if err != nil {
		return fmt.Errorf("failed to create request counter: %w", err)
	}

	inst.requestDuration, err = inst.meter.Float64Histogram(
		"gateway.request.duration",
		metric.WithDescription("Duration of gateway request processing"),
		metric.WithUnit("ms"),
	)
	if err != nil {
		return fmt.Errorf("failed to create request duration histogram: %w", err)
	}

	inst.rateLimitCounter, err = inst.meter.Int64Counter(
		"gateway.ratelimit.exceeded",
		metric.WithDescription("Number of rate-limited requests"),
		metric.WithUnit("{request}"),
	)
	if err != nil {
		return fmt.Errorf("failed to create rate limit counter: %w", err)
	}

	inst.activeConnections, err = inst.meter.Int64UpDownCounter(
		"gateway.connections.active",
		metric.WithDescription("Number of active gateway connections"),
		metric.WithUnit("{connection}"),
	)
	if err != nil {
		return fmt.Errorf("failed to create active connections counter: %w", err)
	}

	inst.upstreamLatency, err = inst.meter.Float64Histogram(
		"gateway.upstream.latency",
		metric.WithDescription("Latency of upstream service calls"),
		metric.WithUnit("ms"),
	)
	if err != nil {
		return fmt.Errorf("failed to create upstream latency histogram: %w", err)
	}

	inst.logger.Info("OTel metrics initialized",
		slog.String("endpoint", inst.config.OTLPEndpoint),
	)
	return nil
}

// Shutdown gracefully shuts down the OTel providers, flushing any pending data.
func (inst *OTelInstrumentation) Shutdown(ctx context.Context) error {
	var errs []error

	if inst.tracerProvider != nil {
		if err := inst.tracerProvider.Shutdown(ctx); err != nil {
			errs = append(errs, fmt.Errorf("tracer provider shutdown: %w", err))
		}
	}

	if inst.meterProvider != nil {
		if err := inst.meterProvider.Shutdown(ctx); err != nil {
			errs = append(errs, fmt.Errorf("meter provider shutdown: %w", err))
		}
	}

	if len(errs) > 0 {
		return fmt.Errorf("otel shutdown errors: %v", errs)
	}

	inst.logger.Info("OTel instrumentation shut down successfully")
	return nil
}

// --- Tracing Helpers ---

// StartSpan starts a new tracing span with the given name and attributes.
func (inst *OTelInstrumentation) StartSpan(ctx context.Context, name string, attrs ...attribute.KeyValue) (context.Context, trace.Span) {
	if inst.tracer == nil {
		return ctx, trace.SpanFromContext(ctx)
	}
	ctx, span := inst.tracer.Start(ctx, name, trace.WithAttributes(attrs...))
	return ctx, span
}

// RecordError records an error on the current span and sets the span status to Error.
func (inst *OTelInstrumentation) RecordError(ctx context.Context, err error) {
	span := trace.SpanFromContext(ctx)
	if span.IsRecording() {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
	}
}

// --- Metrics Helpers ---

// RecordRequest increments the request counter with the given attributes.
func (inst *OTelInstrumentation) RecordRequest(ctx context.Context, method, path, upstream string, statusCode int) {
	if inst.requestCounter == nil {
		return
	}
	inst.requestCounter.Add(ctx, 1,
		metric.WithAttributes(
			attribute.String("http.method", method),
			attribute.String("http.path", path),
			attribute.String("gateway.upstream", upstream),
			attribute.Int("http.status_code", statusCode),
		),
	)
}

// RecordRequestDuration records the duration of a request processing.
func (inst *OTelInstrumentation) RecordRequestDuration(ctx context.Context, method, upstream string, duration time.Duration) {
	if inst.requestDuration == nil {
		return
	}
	inst.requestDuration.Record(ctx, float64(duration.Milliseconds()),
		metric.WithAttributes(
			attribute.String("http.method", method),
			attribute.String("gateway.upstream", upstream),
		),
	)
}

// RecordRateLimitExceeded increments the rate limit counter.
func (inst *OTelInstrumentation) RecordRateLimitExceeded(ctx context.Context, key, policy string) {
	if inst.rateLimitCounter == nil {
		return
	}
	inst.rateLimitCounter.Add(ctx, 1,
		metric.WithAttributes(
			attribute.String("gateway.ratelimit.key", key),
			attribute.String("gateway.ratelimit.policy", policy),
		),
	)
}

// RecordActiveConnection adjusts the active connection counter.
func (inst *OTelInstrumentation) RecordActiveConnection(ctx context.Context, delta int64) {
	if inst.activeConnections == nil {
		return
	}
	inst.activeConnections.Add(ctx, delta)
}

// RecordUpstreamLatency records the latency of an upstream service call.
func (inst *OTelInstrumentation) RecordUpstreamLatency(ctx context.Context, service string, duration time.Duration) {
	if inst.upstreamLatency == nil {
		return
	}
	inst.upstreamLatency.Record(ctx, float64(duration.Milliseconds()),
		metric.WithAttributes(
			attribute.String("gateway.upstream", service),
		),
	)
}

// TracerProvider returns the OTel tracer provider (for gRPC/HTTP interceptors).
func (inst *OTelInstrumentation) TracerProvider() *sdktrace.TracerProvider {
	return inst.tracerProvider
}

// MeterProvider returns the OTel meter provider.
func (inst *OTelInstrumentation) MeterProvider() *sdkmetric.MeterProvider {
	return inst.meterProvider
}
