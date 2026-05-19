// Package observability implements the outbound OpenTelemetry instrumentation
// adapter for the Schema Registry service. It provides tracing, metrics, and
// structured logging instrumentation for all schema registry operations
// including registration, validation, compatibility checking, and Buf CLI
// subprocess execution.
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

// OTelInstrumentation provides OpenTelemetry instrumentation for the Schema
// Registry. It wraps the OTel SDK to provide a simpler interface for creating
// spans, recording metrics, and propagating trace context. All span names
// follow the pattern `schema-registry.{operation}` for consistent querying.
type OTelInstrumentation struct {
	config  OTelConfig
	logger  *slog.Logger

	tracerProvider *sdktrace.TracerProvider
	meterProvider  *sdkmetric.MeterProvider
	tracer         trace.Tracer
	meter          metric.Meter

	// Schema Registry metrics
	registrationCounter  metric.Int64Counter
	validationCounter    metric.Int64Counter
	validationDuration   metric.Float64Histogram
	violationCounter     metric.Int64Counter
	subjectGauge         metric.Int64ObservableGauge
	versionGauge         metric.Int64ObservableGauge
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
			attribute.String("service.namespace", "schema-registry"),
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
		"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry",
		trace.WithInstrumentationVersion(inst.config.ServiceVersion),
	)

	inst.logger.Info("OTel tracing initialized",
		slog.String("endpoint", inst.config.OTLPEndpoint),
		slog.Float64("sample_rate", inst.config.SampleRate),
	)
	return nil
}

// initMetrics initializes the meter provider and registers Schema Registry metrics.
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
		"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry",
		metric.WithInstrumentationVersion(inst.config.ServiceVersion),
	)

	// Register Schema Registry metrics
	inst.registrationCounter, err = inst.meter.Int64Counter(
		"schema.registry.registrations_total",
		metric.WithDescription("Total number of schema registrations"),
		metric.WithUnit("{registration}"),
	)
	if err != nil {
		return fmt.Errorf("failed to create registration counter: %w", err)
	}

	inst.validationCounter, err = inst.meter.Int64Counter(
		"schema.registry.validations_total",
		metric.WithDescription("Total number of schema validations"),
		metric.WithUnit("{validation}"),
	)
	if err != nil {
		return fmt.Errorf("failed to create validation counter: %w", err)
	}

	inst.validationDuration, err = inst.meter.Float64Histogram(
		"schema.registry.validation_duration",
		metric.WithDescription("Duration of schema validation operations"),
		metric.WithUnit("ms"),
	)
	if err != nil {
		return fmt.Errorf("failed to create validation duration histogram: %w", err)
	}

	inst.violationCounter, err = inst.meter.Int64Counter(
		"schema.registry.violations_total",
		metric.WithDescription("Total number of compatibility violations detected"),
		metric.WithUnit("{violation}"),
	)
	if err != nil {
		return fmt.Errorf("failed to create violation counter: %w", err)
	}

	inst.subjectGauge, err = inst.meter.Int64ObservableGauge(
		"schema.registry.subjects",
		metric.WithDescription("Number of registered schema subjects"),
		metric.WithUnit("{subject}"),
	)
	if err != nil {
		return fmt.Errorf("failed to create subject gauge: %w", err)
	}

	inst.versionGauge, err = inst.meter.Int64ObservableGauge(
		"schema.registry.versions",
		metric.WithDescription("Total number of registered schema versions"),
		metric.WithUnit("{version}"),
	)
	if err != nil {
		return fmt.Errorf("failed to create version gauge: %w", err)
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
// Span names follow the `schema-registry.{operation}` pattern for
// consistent querying and dashboarding.
func (inst *OTelInstrumentation) StartSpan(ctx context.Context, name string, attrs ...attribute.KeyValue) (context.Context, trace.Span) {
	if inst.tracer == nil {
		return ctx, trace.SpanFromContext(ctx)
	}
	ctx, span := inst.tracer.Start(ctx, "schema-registry."+name, trace.WithAttributes(attrs...))
	return ctx, span
}

// RecordError records an error on the current span and sets the span status.
func (inst *OTelInstrumentation) RecordError(ctx context.Context, err error) {
	span := trace.SpanFromContext(ctx)
	if span.IsRecording() {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
	}
}

// --- Metrics Helpers ---

// RecordRegistration increments the registration counter with the given attributes.
func (inst *OTelInstrumentation) RecordRegistration(ctx context.Context, subject, schemaType, result string) {
	if inst.registrationCounter == nil {
		return
	}
	inst.registrationCounter.Add(ctx, 1,
		metric.WithAttributes(
			attribute.String("subject", subject),
			attribute.String("schema_type", schemaType),
			attribute.String("result", result),
		),
	)
}

// RecordValidation increments the validation counter and records duration.
func (inst *OTelInstrumentation) RecordValidation(ctx context.Context, level, result string, duration time.Duration) {
	if inst.validationCounter == nil {
		return
	}
	inst.validationCounter.Add(ctx, 1,
		metric.WithAttributes(
			attribute.String("level", level),
			attribute.String("result", result),
		),
	)
	if inst.validationDuration != nil {
		inst.validationDuration.Record(ctx, float64(duration.Milliseconds()),
			metric.WithAttributes(
				attribute.String("level", level),
			),
		)
	}
}

// RecordViolation increments the compatibility violation counter.
func (inst *OTelInstrumentation) RecordViolation(ctx context.Context, subject, violationType string) {
	if inst.violationCounter == nil {
		return
	}
	inst.violationCounter.Add(ctx, 1,
		metric.WithAttributes(
			attribute.String("subject", subject),
			attribute.String("type", violationType),
		),
	)
}

// TracerProvider returns the OTel tracer provider for gRPC/HTTP interceptors.
func (inst *OTelInstrumentation) TracerProvider() *sdktrace.TracerProvider {
	return inst.tracerProvider
}

// MeterProvider returns the OTel meter provider.
func (inst *OTelInstrumentation) MeterProvider() *sdkmetric.MeterProvider {
	return inst.meterProvider
}
