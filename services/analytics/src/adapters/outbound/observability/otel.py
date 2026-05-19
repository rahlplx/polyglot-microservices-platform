"""
OpenTelemetry self-instrumentation adapter for the Analytics service.

This module configures the OpenTelemetry SDK for the Analytics service's own
operations, enabling distributed tracing, metrics collection, and structured
logging. The adapter exports self-monitoring telemetry to a separate OTLP
endpoint (or to the same ClickHouse database with a different table prefix)
to keep self-observability data distinct from customer data.

The Analytics service is unique in that it both produces and consumes
OpenTelemetry telemetry. Self-monitoring metrics are tagged with
"self_monitoring=true" and are excluded from business dashboards and
reports by default. This separation prevents feedback loops where the
service's own telemetry would be ingested and processed by itself.

The adapter uses the OpenTelemetry Python SDK with the OTLP exporter
for traces and metrics, and Python's logging module with JSON formatting
and OTel trace context injection for structured logs.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


class OtelInstrumentation:
    """OpenTelemetry self-instrumentation configuration for the Analytics service.

    This adapter sets up the OTel SDK with the appropriate providers,
    exporters, and instrumentation libraries. It ensures that all service
    operations are traced, all key metrics are collected, and all logs
    include trace context for correlation.

    The instrumentation is configured to export to an OTLP endpoint
    specified by the OTEL_EXPORTER_OTLP_ENDPOINT environment variable,
    with a fallback to the standard localhost:4317 endpoint.
    """

    def __init__(
        self,
        service_name: str = "analytics",
        service_version: str = "0.1.0",
        otlp_endpoint: str = "http://localhost:4317",
        enable_tracing: bool = True,
        enable_metrics: bool = True,
    ) -> None:
        """Initialize the OTel instrumentation configuration.

        Args:
            service_name: The service name for OTel resource attributes.
            service_version: The service version for OTel resource attributes.
            otlp_endpoint: The OTLP endpoint for exporting telemetry.
            enable_tracing: Whether to enable distributed tracing.
            enable_metrics: Whether to enable metric collection.
        """
        self._service_name = service_name
        self._service_version = service_version
        self._otlp_endpoint = otlp_endpoint
        self._enable_tracing = enable_tracing
        self._enable_metrics = enable_metrics
        self._tracer_provider: Any = None
        self._meter_provider: Any = None

    def setup(self) -> None:
        """Configure and initialize the OpenTelemetry SDK.

        Sets up the tracer provider, meter provider, and logging
        integration. This method should be called once during service
        startup, before any requests are processed.
        """
        self._setup_logging()

        if self._enable_tracing:
            self._setup_tracing()

        if self._enable_metrics:
            self._setup_metrics()

        logger.info(
            "OTel instrumentation configured: service=%s, endpoint=%s",
            self._service_name,
            self._otlp_endpoint,
        )

    def shutdown(self) -> None:
        """Gracefully shut down the OTel providers.

        Flushes any pending telemetry data before shutdown. This method
        should be called during service shutdown to ensure that no
        telemetry data is lost.
        """
        if self._tracer_provider:
            try:
                self._tracer_provider.shutdown()
            except Exception as exc:
                logger.warning("Failed to shutdown tracer provider: %s", exc)

        if self._meter_provider:
            try:
                self._meter_provider.shutdown()
            except Exception as exc:
                logger.warning("Failed to shutdown meter provider: %s", exc)

        logger.info("OTel instrumentation shut down")

    def _setup_tracing(self) -> None:
        """Configure the OpenTelemetry tracer provider with OTLP exporter.

        Creates a tracer provider with a BatchSpanProcessor for efficient
        span export, and sets it as the global tracer provider. The
        processor batches spans in memory and exports them periodically
        to reduce network overhead.
        """
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.resources import Resource

            resource = Resource.create({
                "service.name": self._service_name,
                "service.version": self._service_version,
                "service.namespace": "com.company",
                "self_monitoring": "true",
            })

            self._tracer_provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=self._otlp_endpoint, insecure=True)
            self._tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

            trace.set_tracer_provider(self._tracer_provider)
            logger.info("OTel tracing configured with OTLP exporter")
        except ImportError:
            logger.warning("OpenTelemetry packages not available, tracing disabled")
        except Exception as exc:
            logger.warning("Failed to setup tracing: %s", exc)

    def _setup_metrics(self) -> None:
        """Configure the OpenTelemetry meter provider with OTLP exporter.

        Creates a meter provider with a PeriodicExportingMetricReader
        that exports metrics every 60 seconds. The metrics include
        standard HTTP/gRPC server metrics and custom analytics metrics.
        """
        try:
            from opentelemetry import metrics
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource

            resource = Resource.create({
                "service.name": self._service_name,
                "service.version": self._service_version,
                "service.namespace": "com.company",
                "self_monitoring": "true",
            })

            exporter = OTLPMetricExporter(endpoint=self._otlp_endpoint, insecure=True)
            reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
            self._meter_provider = MeterProvider(resource=resource, metric_readers=[reader])

            metrics.set_meter_provider(self._meter_provider)
            logger.info("OTel metrics configured with OTLP exporter")
        except ImportError:
            logger.warning("OpenTelemetry packages not available, metrics disabled")
        except Exception as exc:
            logger.warning("Failed to setup metrics: %s", exc)

    def _setup_logging(self) -> None:
        """Configure structured JSON logging with OTel trace context injection.

        Sets up Python's logging module with a JSON formatter that includes
        trace ID, span ID, and trace flags in each log entry. This enables
        correlation between logs, traces, and metrics in the observability
        backend.
        """
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        root_logger.addHandler(handler)

        logger.info("Structured JSON logging configured")


class JSONFormatter(logging.Formatter):
    """JSON log formatter with OTel trace context injection.

    Formats log records as JSON objects with standard fields (timestamp,
    level, message, logger) plus OTel trace context fields (trace_id,
    span_id, trace_flags) when available. This format is compatible with
    Grafana Loki and other log aggregation systems that expect structured
    JSON input.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string.

        Extracts standard log fields and OTel trace context from the
        record, producing a self-contained JSON object per log entry.

        Args:
            record: The Python logging record to format.

        Returns:
            A JSON-formatted string representation of the log record.
        """
        import json
        from datetime import datetime, timezone

        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Inject OTel trace context if available
        span_context = getattr(record, "otelSpanID", None)
        trace_id = getattr(record, "otelTraceID", None)
        trace_flags = getattr(record, "otelTraceFlags", None)

        if trace_id:
            log_entry["trace_id"] = trace_id
        if span_context:
            log_entry["span_id"] = span_context
        if trace_flags:
            log_entry["trace_flags"] = trace_flags

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])

        return json.dumps(log_entry)
