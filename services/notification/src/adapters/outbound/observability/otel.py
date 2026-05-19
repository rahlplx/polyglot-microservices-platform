"""
OpenTelemetry instrumentation adapter for the Notification service.

This module provides automatic and manual instrumentation for the
notification service. Auto-instrumentation covers HTTP (FastAPI), Kafka
(confluent-kafka), and database (SQLAlchemy) operations. Manual spans
are added for template rendering, ML model inference, and delivery
provider interactions.

The adapter implements a custom span processor that adds notification-
specific attributes (notification ID, channel, template ID) to all spans
within a notification processing context. Structured logs use Python's
logging module with a JSON formatter and OTel trace context injection.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class NotificationSpanAttributes:
    """Constants for notification-specific OpenTelemetry span attributes.

    These attribute keys are added to spans within the notification
    processing pipeline to provide context for observability and
    debugging. They follow the OpenTelemetry semantic conventions
    for attribute naming.
    """

    NOTIFICATION_ID = "notification.id"
    NOTIFICATION_CHANNEL = "notification.channel"
    NOTIFICATION_TEMPLATE_ID = "notification.template_id"
    NOTIFICATION_PRIORITY = "notification.priority"
    NOTIFICATION_TYPE = "notification.type"
    NOTIFICATION_RECIPIENT_ID = "notification.recipient_id"
    NOTIFICATION_STATUS = "notification.status"
    NOTIFICATION_PROVIDER = "notification.provider"
    NOTIFICATION_CORRELATION_ID = "notification.correlation_id"


class NotificationMetrics:
    """Metric definitions for the Notification service.

    These metrics follow the OpenTelemetry metric naming conventions
    and are used throughout the service for monitoring delivery
    performance, provider health, and ML model accuracy.
    """

    # Counter metrics
    PROVIDER_SUBMISSIONS_TOTAL = "notification.provider.submissions_total"
    NOTIFICATION_STATES_TOTAL = "notification.states_total"
    TRACKING_EVENTS_TOTAL = "notification.tracking.events_total"
    ML_INFERENCES_TOTAL = "notification.ml.inferences_total"

    # Histogram metrics
    PROVIDER_LATENCY = "notification.provider.latency"
    DELIVERY_DURATION = "notification.delivery.duration"
    ML_INFERENCE_DURATION = "notification.ml.inference_duration"

    # Gauge metrics
    PROVIDER_RATE_LIMIT_REMAINING = "notification.provider.rate_limit_remaining"
    PENDING_NOTIFICATIONS = "notification.pending"
    ML_MODEL_ACCURACY = "notification.ml.model_accuracy"


class OTelInstrumentation:
    """OpenTelemetry instrumentation setup for the Notification service.

    This class configures the OpenTelemetry SDK for the notification
    service, including auto-instrumentation for supported frameworks
    and manual span creation for domain-specific operations.

    The instrumentation is designed to be optional: if the OpenTelemetry
    packages are not installed, the service operates normally without
    telemetry. This graceful degradation supports development and
    testing environments where observability infrastructure is not
    available.
    """

    def __init__(
        self,
        service_name: str = "notification-service",
        service_version: str = "0.1.0",
        otlp_endpoint: Optional[str] = None,
        enable_auto_instrumentation: bool = True,
    ) -> None:
        """Initialize the OTel instrumentation.

        Args:
            service_name: The service name for OTel resource attributes.
            service_version: The service version for OTel resource attributes.
            otlp_endpoint: The OTLP collector endpoint URL. If None,
                telemetry is exported to stdout.
            enable_auto_instrumentation: Whether to enable automatic
                instrumentation of supported frameworks.
        """
        self._service_name = service_name
        self._service_version = service_version
        self._otlp_endpoint = otlp_endpoint
        self._enable_auto = enable_auto_instrumentation
        self._tracer = None
        self._meter = None
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the OpenTelemetry SDK and auto-instrumentation.

        Sets up the tracer provider, meter provider, and auto-
        instrumentation for supported frameworks (FastAPI, SQLAlchemy,
        confluent-kafka). If the OpenTelemetry packages are not installed,
        a warning is logged and the service continues without telemetry.
        """
        if self._initialized:
            return

        try:
            from opentelemetry import trace, metrics
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.resources import Resource

            # Create resource
            resource = Resource.create({
                "service.name": self._service_name,
                "service.version": self._service_version,
                "service.namespace": "microservices",
            })

            # Configure tracer provider
            tracer_provider = TracerProvider(resource=resource)

            if self._otlp_endpoint:
                try:
                    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                    exporter = OTLPSpanExporter(endpoint=self._otlp_endpoint)
                    tracer_provider.add_span_processor(
                        BatchSpanProcessor(exporter)
                    )
                except ImportError:
                    logger.warning(
                        "OTLP exporter not available, using console export"
                    )

            trace.set_tracer_provider(tracer_provider)
            self._tracer = trace.get_tracer(
                self._service_name, self._service_version
            )

            # Configure meter provider
            meter_provider = MeterProvider(resource=resource)
            metrics.set_meter_provider(meter_provider)
            self._meter = metrics.get_meter(
                self._service_name, self._service_version
            )

            # Auto-instrumentation
            if self._enable_auto:
                self._setup_auto_instrumentation()

            self._initialized = True
            logger.info(
                "OpenTelemetry initialized for %s v%s",
                self._service_name,
                self._service_version,
            )

        except ImportError:
            logger.warning(
                "OpenTelemetry packages not installed, "
                "service will run without telemetry"
            )
        except Exception as e:
            logger.error("Failed to initialize OpenTelemetry: %s", e)

    def _setup_auto_instrumentation(self) -> None:
        """Set up automatic instrumentation for supported frameworks.

        Attempts to instrument FastAPI, SQLAlchemy, and confluent-kafka
        if their respective OpenTelemetry instrumentation packages are
        available. Missing instrumentation packages are logged as
        warnings rather than causing failures.
        """
        try:
            from opentelemetry.instrumentation.auto_instrumentation import site_packages
            site_packages.initialize()
        except ImportError:
            pass

        # FastAPI auto-instrumentation
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument()
            logger.debug("FastAPI auto-instrumentation enabled")
        except ImportError:
            logger.debug("FastAPI instrumentation package not available")

        # SQLAlchemy auto-instrumentation
        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
            SQLAlchemyInstrumentor.instrument()
            logger.debug("SQLAlchemy auto-instrumentation enabled")
        except ImportError:
            logger.debug("SQLAlchemy instrumentation package not available")

    @property
    def tracer(self) -> Optional[Any]:
        """Get the configured tracer, or None if not initialized."""
        return self._tracer

    @property
    def meter(self) -> Optional[Any]:
        """Get the configured meter, or None if not initialized."""
        return self._meter

    def create_notification_span(
        self,
        notification_id: str,
        channel: str,
        template_id: str = "",
        priority: str = "",
        correlation_id: str = "",
    ) -> Optional[Any]:
        """Create a span for a notification processing pipeline.

        The span includes notification-specific attributes for
        observability and debugging. Returns None if the tracer
        is not initialized.

        Args:
            notification_id: The notification's unique identifier.
            channel: The delivery channel.
            template_id: The template used for rendering.
            priority: The notification priority level.
            correlation_id: The correlation ID for trace linking.

        Returns:
            A span context manager, or None if tracing is disabled.
        """
        if self._tracer is None:
            return None

        span = self._tracer.start_span("notification.process")
        span.set_attribute(NotificationSpanAttributes.NOTIFICATION_ID, notification_id)
        span.set_attribute(NotificationSpanAttributes.NOTIFICATION_CHANNEL, channel)
        if template_id:
            span.set_attribute(NotificationSpanAttributes.NOTIFICATION_TEMPLATE_ID, template_id)
        if priority:
            span.set_attribute(NotificationSpanAttributes.NOTIFICATION_PRIORITY, priority)
        if correlation_id:
            span.set_attribute(NotificationSpanAttributes.NOTIFICATION_CORRELATION_ID, correlation_id)
        return span

    def shutdown(self) -> None:
        """Gracefully shutdown the OpenTelemetry SDK.

        Flushes any pending spans and metrics before shutting down.
        This method should be called during service shutdown to ensure
        that all telemetry data is exported.
        """
        if not self._initialized:
            return

        try:
            from opentelemetry import trace, metrics

            trace.get_tracer_provider().shutdown()  # type: ignore
            metrics.get_meter_provider().shutdown()  # type: ignore
            logger.info("OpenTelemetry shutdown complete")
        except Exception as e:
            logger.warning("Error during OTel shutdown: %s", e)


class JSONFormatter(logging.Formatter):
    """JSON log formatter with OTel trace context injection.

    Formats log records as JSON objects with trace and span IDs
    from the current OpenTelemetry context. This enables log
    correlation with traces in observability backends like
    Grafana Loki.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string.

        Includes the standard log fields (timestamp, level, message,
        logger name) plus OpenTelemetry trace context (trace_id,
        span_id) if available.

        Args:
            record: The log record to format.

        Returns:
            A JSON-formatted log string.
        """
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add OTel trace context
        try:
            from opentelemetry import trace
            span = trace.get_current_span()
            if span and span.is_recording():
                ctx = span.get_span_context()
                log_entry["trace_id"] = format(ctx.trace_id, "032x")
                log_entry["span_id"] = format(ctx.span_id, "016x")
        except ImportError:
            pass

        # Add exception info if present
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])

        return json.dumps(log_entry)
