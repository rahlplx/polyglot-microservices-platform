package com.company.order.adapters.outbound.observability

import io.opentelemetry.api.OpenTelemetry
import io.opentelemetry.api.common.Attributes
import io.opentelemetry.api.metrics.LongCounter
import io.opentelemetry.api.metrics.LongHistogram
import io.opentelemetry.api.metrics.Meter
import io.opentelemetry.api.trace.Span
import io.opentelemetry.api.trace.Tracer
import io.opentelemetry.api.trace.StatusCode
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator
import io.opentelemetry.context.propagation.ContextPropagators
import io.opentelemetry.exporter.otlp.metrics.OtlpGrpcMetricExporter
import io.opentelemetry.exporter.otlp.trace.OtlpGrpcSpanExporter
import io.opentelemetry.sdk.OpenTelemetrySdk
import io.opentelemetry.sdk.metrics.SdkMeterProvider
import io.opentelemetry.sdk.metrics.export.PeriodicMetricReader
import io.opentelemetry.sdk.resources.Resource
import io.opentelemetry.sdk.trace.SdkTracerProvider
import io.opentelemetry.sdk.trace.export.BatchSpanProcessor
import io.opentelemetry.sdk.trace.export.SimpleSpanProcessor
import io.opentelemetry.semconv.ServiceAttributes
import org.slf4j.LoggerFactory
import java.time.Duration

/**
 * OpenTelemetry adapter for the Order service.
 *
 * Provides tracing, metrics, and context propagation for:
 * - gRPC request tracing (server spans)
 * - Saga execution tracing (with step-level granularity)
 * - Database operation tracing (jOOQ query spans)
 * - Kafka producer/consumer tracing
 * - Custom order metrics (transitions, fulfillment duration, active sagas)
 *
 * Configuration supports:
 * - OTLP gRPC export for traces and metrics
 * - W3C Trace Context propagation for distributed tracing
 * - Tail-based sampling (configured at the collector level)
 * - Custom metrics aligned with performance-budget.md
 */
class OtelAdapter(
    private val serviceName: String = "order-service",
    private val serviceVersion: String = "1.0.0",
    private val otlpEndpoint: String = "http://localhost:4317",
    private val enableLoggingExporter: Boolean = false
) {
    private val logger = LoggerFactory.getLogger(OtelAdapter::class.java)

    private val resource: Resource = Resource.builder()
        .put(ServiceAttributes.SERVICE_NAME, serviceName)
        .put(ServiceAttributes.SERVICE_VERSION, serviceVersion)
        .build()

    private val sdkTracerProvider: SdkTracerProvider = SdkTracerProvider.builder()
        .setResource(resource)
        .addSpanProcessor(
            BatchSpanProcessor.builder(
                OtlpGrpcSpanExporter.builder()
                    .setEndpoint(otlpEndpoint)
                    .setTimeout(Duration.ofSeconds(10))
                    .build()
            ).build()
        )
        .also { builder ->
            if (enableLoggingExporter) {
                builder.addSpanProcessor(
                    SimpleSpanProcessor.create(
                        io.opentelemetry.exporter.logging.LoggingSpanExporter.create()
                    )
                )
            }
        }
        .build()

    private val sdkMeterProvider: SdkMeterProvider = SdkMeterProvider.builder()
        .setResource(resource)
        .registerMetricReader(
            PeriodicMetricReader.builder(
                OtlpGrpcMetricExporter.builder()
                    .setEndpoint(otlpEndpoint)
                    .setTimeout(Duration.ofSeconds(10))
                    .build()
            )
            .setInterval(Duration.ofSeconds(15))
            .build()
        )
        .build()

    val openTelemetry: OpenTelemetry = OpenTelemetrySdk.builder()
        .setTracerProvider(sdkTracerProvider)
        .setMeterProvider(sdkMeterProvider)
        .setPropagators(ContextPropagators.create(W3CTraceContextPropagator.getInstance()))
        .build()

    val tracer: Tracer = openTelemetry.getTracer(serviceName, serviceVersion)
    val meter: Meter = openTelemetry.getMeter(serviceName)

    // --- Custom Metrics ---

    /** Counter for order state transitions */
    val orderTransitionsCounter: LongCounter = meter.counterBuilder("order.transitions.total")
        .setDescription("Number of order state transitions")
        .setUnit("1")
        .build()

    /** Histogram for order fulfillment duration */
    val fulfillmentDurationHistogram: LongHistogram = meter.histogramBuilder("order.fulfillment.duration")
        .setDescription("Duration of order fulfillment from creation to completion")
        .setUnit("ms")
        .ofLongs()
        .build()

    /** Counter for saga compensations */
    val sagaCompensationsCounter: LongCounter = meter.counterBuilder("order.saga.compensations.total")
        .setDescription("Number of saga compensation actions executed")
        .setUnit("1")
        .build()

    /** Counter for outbox relay operations */
    val outboxRelayCounter: LongCounter = meter.counterBuilder("order.outbox.relay.total")
        .setDescription("Number of outbox entries relayed to Kafka")
        .setUnit("1")
        .build()

    // --- Tracing Helpers ---

    /**
     * Create a span for a saga execution step.
     */
    fun createSagaStepSpan(
        sagaId: String,
        orderId: String,
        stepName: String,
        parentSpan: Span? = null
    ): Span {
        val spanBuilder = tracer.spanBuilder("saga.step.$stepName")
            .setAttribute("saga.id", sagaId)
            .setAttribute("order.id", orderId)
            .setAttribute("saga.step", stepName)

        val span = spanBuilder.startSpan()
        logger.debug("Created saga step span: step=$stepName, sagaId=$sagaId")
        return span
    }

    /**
     * Record an order state transition metric.
     */
    fun recordOrderTransition(fromStatus: String, toStatus: String) {
        orderTransitionsCounter.add(
            1,
            Attributes.builder()
                .put("from_status", fromStatus)
                .put("to_status", toStatus)
                .build()
        )
    }

    /**
     * Record a saga compensation metric.
     */
    fun recordSagaCompensation(stepName: String, reason: String) {
        sagaCompensationsCounter.add(
            1,
            Attributes.builder()
                .put("step", stepName)
                .put("reason", reason)
                .build()
        )
    }

    /**
     * Record an outbox relay operation.
     */
    fun recordOutboxRelay(count: Int) {
        outboxRelayCounter.add(count.toLong())
    }

    /**
     * Record an error on a span.
     */
    fun recordSpanError(span: Span, error: Throwable) {
        span.setStatus(StatusCode.ERROR, error.message)
        span.recordException(error)
    }

    /**
     * Shut down the OpenTelemetry SDK gracefully.
     */
    fun shutdown() {
        logger.info("Shutting down OpenTelemetry SDK")
        sdkTracerProvider.shutdown()
        sdkMeterProvider.shutdown()
    }
}
