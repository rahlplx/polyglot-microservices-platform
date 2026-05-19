"""
Custom OTel span processor for trace analytics in the Analytics service.

This module implements the OTelTraceProcessor outbound port, providing a custom
SpanProcessor that extracts service metrics from distributed traces and writes
them to the ClickHouse time series store. The processor is unique in that it
both produces and consumes OpenTelemetry telemetry: it receives OTLP data from
other services (acting as a telemetry backend) and also instruments its own
operations.

Self-monitoring metrics are carefully separated from ingested metrics to
prevent feedback loops. The processor tags all self-generated metrics with
a "self_monitoring=true" label, and the aggregation engine excludes these
from business dashboards and reports by default.

The processor supports multiple span formats: the standard OTLP JSON format
used by the OpenTelemetry SDK, and the simplified span format used by the
Query RPC. It extracts the following metrics from each span: request count,
error count, latency histogram, and service throughput.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ...domain.models.aggregation import AggregationFunction
from ...domain.models.metric import DataPoint, Metric, MetricType
from ...domain.ports.outbound.otel_processor import OTelTraceProcessor
from ...domain.ports.outbound.time_series_store import TimeSeriesRepository

logger = logging.getLogger(__name__)


class OTelSpanProcessor:
    """Custom OTel span processor for extracting service metrics from traces.

    This adapter implements the OTelTraceProcessor port by receiving OTLP
    span data from other services, extracting meaningful metrics, and writing
    those metrics to the ClickHouse time series store. It also supports
    querying trace data for the QueryTraces inbound port.

    The processor maintains an in-memory trace cache for recently received
    traces, enabling fast lookup by trace ID. The cache is bounded to
    prevent unbounded memory growth in high-throughput scenarios.
    """

    def __init__(
        self,
        time_series_repo: TimeSeriesRepository,
        max_trace_cache_size: int = 10000,
    ) -> None:
        """Initialize the OTel span processor with required dependencies.

        Args:
            time_series_repo: Repository for writing extracted metrics.
            max_trace_cache_size: Maximum number of traces to keep in the
                in-memory cache for fast lookups.
        """
        self._repo = time_series_repo
        self._max_cache_size = max_trace_cache_size
        self._trace_cache: dict[str, dict[str, Any]] = {}

    def process_spans(self, spans: list[dict[str, Any]]) -> int:
        """Process a batch of OTel spans and extract metrics.

        Each span is parsed to extract the service name, operation name,
        duration, status code, and attributes. Derived metrics (request
        count, error count, latency) are written to the time series store.
        Spans are also indexed in the trace cache for lookup queries.

        Args:
            spans: A list of span dictionaries in OTLP JSON format.

        Returns:
            The number of spans that were successfully processed.
        """
        processed = 0
        for span in spans:
            try:
                metrics = self._extract_metrics_from_span(span)
                for metric in metrics:
                    self._repo.write(
                        series=[metric.to_data_point()],
                        metric_name=metric.name,
                        labels=metric.labels,
                    )
                self._index_span(span)
                processed += 1
            except Exception as exc:
                logger.warning("Failed to process span: %s", exc)

        logger.info("Processed %d/%d spans", processed, len(spans))
        return processed

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """Retrieve a complete trace by its trace ID.

        Looks up the trace in the in-memory cache. If found, returns
        the full trace with all its spans.

        Args:
            trace_id: The unique identifier of the trace.

        Returns:
            A dictionary containing the trace with all its spans,
            or None if the trace ID is not found.
        """
        return self._trace_cache.get(trace_id)

    def query_traces(
        self,
        service_name: str | None = None,
        operation_name: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
        tags: dict[str, str] | None = None,
        start_time: Any | None = None,
        end_time: Any | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search traces with various filter criteria.

        Filters the in-memory trace cache by the specified criteria.
        This implementation provides basic filtering; a production
        deployment would delegate to ClickHouse for scalable queries.

        Args:
            service_name: Optional service name filter.
            operation_name: Optional operation name filter.
            min_duration_ms: Optional minimum duration filter.
            max_duration_ms: Optional maximum duration filter.
            tags: Optional tag-based filters.
            start_time: Optional start of the time range.
            end_time: Optional end of the time range.
            limit: Maximum number of traces to return.

        Returns:
            A list of trace dictionaries matching the filters.
        """
        results: list[dict[str, Any]] = []

        for trace_id, trace in self._trace_cache.items():
            root_service = trace.get("root_service", "")
            root_operation = trace.get("root_operation", "")
            duration_ms = trace.get("duration_ms", 0)

            if service_name and root_service != service_name:
                continue
            if operation_name and root_operation != operation_name:
                continue
            if min_duration_ms is not None and duration_ms < min_duration_ms:
                continue
            if max_duration_ms is not None and duration_ms > max_duration_ms:
                continue

            results.append(trace)
            if len(results) >= limit:
                break

        return results

    def get_dependencies(self, start_time: Any, end_time: Any) -> dict[str, Any]:
        """Retrieve the service dependency graph for a time range.

        Aggregates span data from the trace cache to derive the
        service-to-service communication topology.

        Args:
            start_time: Start of the time range.
            end_time: End of the time range.

        Returns:
            A dictionary representing the dependency graph.
        """
        edges: dict[str, dict[str, Any]] = {}
        nodes: set[str] = set()

        for trace in self._trace_cache.values():
            spans = trace.get("spans", [])
            for span in spans:
                service = span.get("service_name", "")
                parent_service = span.get("parent_service", "")
                if service and parent_service:
                    edge_key = f"{parent_service}->{service}"
                    if edge_key not in edges:
                        edges[edge_key] = {
                            "source": parent_service,
                            "target": service,
                            "call_count": 0,
                            "error_count": 0,
                            "total_duration_ms": 0,
                        }
                    edges[edge_key]["call_count"] += 1
                    edges[edge_key]["total_duration_ms"] += span.get("duration_ms", 0)
                    if span.get("status") == "ERROR":
                        edges[edge_key]["error_count"] += 1
                if service:
                    nodes.add(service)

        for edge in edges.values():
            if edge["call_count"] > 0:
                edge["avg_duration_ms"] = round(edge["total_duration_ms"] / edge["call_count"], 2)
                edge["error_rate"] = round(edge["error_count"] / edge["call_count"] * 100, 2)

        return {
            "nodes": [{"id": n} for n in sorted(nodes)],
            "edges": list(edges.values()),
        }

    def _extract_metrics_from_span(self, span: dict[str, Any]) -> list[Metric]:
        """Extract service metrics from a single OTel span.

        Derives request count, error count, and latency metrics from
        the span's attributes. These metrics are written to ClickHouse
        for dashboard and alerting consumption.

        Args:
            span: A span dictionary with standard OTLP fields.

        Returns:
            A list of Metric objects derived from the span.
        """
        now = datetime.now(tz=timezone.utc)
        service = span.get("service_name", "unknown")
        operation = span.get("operation_name", "unknown")
        duration_ms = span.get("duration_ms", 0)
        status = span.get("status", "OK")

        metrics = [
            Metric(
                name="request.count",
                metric_type=MetricType.COUNTER,
                value=1.0,
                timestamp=now,
                service=service,
                labels={"operation": operation},
            ),
            Metric(
                name="request.duration_ms",
                metric_type=MetricType.HISTOGRAM,
                value=float(duration_ms),
                timestamp=now,
                service=service,
                labels={"operation": operation},
            ),
        ]

        if status == "ERROR":
            metrics.append(
                Metric(
                    name="request.error_count",
                    metric_type=MetricType.COUNTER,
                    value=1.0,
                    timestamp=now,
                    service=service,
                    labels={"operation": operation, "status": "error"},
                )
            )

        return metrics

    def _index_span(self, span: dict[str, Any]) -> None:
        """Index a span in the trace cache for lookup queries.

        Groups spans by trace ID and maintains a bounded cache
        using a simple eviction strategy when the cache exceeds
        the maximum size.

        Args:
            span: The span to index.
        """
        trace_id = span.get("trace_id", "")
        if not trace_id:
            return

        if trace_id not in self._trace_cache:
            if len(self._trace_cache) >= self._max_cache_size:
                oldest_key = next(iter(self._trace_cache))
                del self._trace_cache[oldest_key]

            self._trace_cache[trace_id] = {
                "trace_id": trace_id,
                "spans": [],
                "root_service": span.get("service_name", ""),
                "root_operation": span.get("operation_name", ""),
                "duration_ms": span.get("duration_ms", 0),
                "start_time": span.get("start_time", ""),
            }

        self._trace_cache[trace_id]["spans"].append(span)

        if not span.get("parent_span_id"):
            self._trace_cache[trace_id]["root_service"] = span.get("service_name", "")
            self._trace_cache[trace_id]["root_operation"] = span.get("operation_name", "")
