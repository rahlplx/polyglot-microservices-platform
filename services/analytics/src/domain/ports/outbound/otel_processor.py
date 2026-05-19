"""
OpenTelemetry trace processor port for the Analytics service.

This module defines the OTelTraceProcessor protocol, which is the outbound
port for processing OpenTelemetry trace data received from other services.
The analytics service acts as both a producer and consumer of OTel telemetry:
it receives OTLP data from other services' OTel SDKs and extracts service
metrics from traces for storage in the time series database.

The processor is responsible for parsing span data, extracting meaningful
metrics (request latency, error rates, throughput), and writing those
metrics to the time series store. Self-monitoring telemetry is carefully
separated from ingested telemetry to prevent feedback loops.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class OTelTraceProcessor(Protocol):
    """Outbound port for processing OpenTelemetry trace data.

    This protocol defines the contract for receiving and processing OTel
    spans from other services. The processor extracts service-level metrics
    from trace data (latency percentiles, error rates, request throughput)
    and writes them to the time series store. It also supports querying
    trace data for the QueryTraces inbound port.
    """

    def process_spans(self, spans: list[dict[str, Any]]) -> int:
        """Process a batch of OTel spans and extract metrics.

        Each span is parsed to extract the service name, operation name,
        duration, status code, and attributes. Derived metrics (request
        count, error count, latency histogram) are written to the time
        series store. The method returns the count of successfully
        processed spans for monitoring and alerting.

        Args:
            spans: A list of span dictionaries in OTLP JSON format.

        Returns:
            The number of spans that were successfully processed and
            had their metrics written to the time series store.

        Raises:
            SpanProcessingError: If the batch cannot be processed.
        """
        ...

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """Retrieve a complete trace by its trace ID.

        Returns the full span tree for a trace, with parent-child
        relationships preserved. Used by the QueryTraces port for
        direct trace lookup.

        Args:
            trace_id: The unique identifier of the trace.

        Returns:
            A dictionary containing the trace with all its spans,
            or None if the trace ID is not found.
        """
        ...

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

        Supports multiple query modes: service-based, operation-based,
        duration-range, and tag-based filtering. Returns matching traces
        with their full span trees.

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
        ...

    def get_dependencies(self, start_time: Any, end_time: Any) -> dict[str, Any]:
        """Retrieve the service dependency graph for a time range.

        Aggregates span data to derive the service-to-service communication
        topology, showing which services call which other services and the
        latency distributions of those calls.

        Args:
            start_time: Start of the time range.
            end_time: End of the time range.

        Returns:
            A dictionary representing the dependency graph with nodes
            (services) and edges (service-to-service calls) including
            latency percentiles and error rates.
        """
        ...
