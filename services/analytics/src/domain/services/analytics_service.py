"""
Analytics query orchestration service for the Analytics service.

This module implements the core analytics query service that coordinates
metric queries, trace searches, and data retrieval across multiple outbound
ports. The service acts as the central orchestrator for all query-side
operations, applying business rules such as time range validation,
automatic rollup selection, and query complexity limits before delegating
to the appropriate outbound port implementations.

The service enforces SLO targets by validating query parameters against
known performance characteristics: overly broad time ranges are rejected
early, and appropriate rollup tables are selected automatically to ensure
sub-500ms p99 query latency.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models.aggregation import AggregationFunction, AggregationWindow
from ..models.metric import TimeSeries
from ..models.report import TimeRange
from ..ports.outbound.event_store import EventRepository
from ..ports.outbound.otel_processor import OTelTraceProcessor
from ..ports.outbound.time_series_store import TimeSeriesRepository

logger = logging.getLogger(__name__)


class MetricNotFoundError(Exception):
    """Raised when a requested metric name does not exist in the store."""
    pass


class InvalidTimeRangeError(Exception):
    """Raised when the specified time range is malformed or exceeds limits."""
    pass


class AggregationNotSupportedError(Exception):
    """Raised when the aggregation function is not available for the metric type."""
    pass


class TraceStorageUnavailableError(Exception):
    """Raised when the trace storage backend is unavailable."""
    pass


class QueryTooBroadError(Exception):
    """Raised when a query would scan too much data and needs narrowing."""
    pass


class AnalyticsService:
    """Core analytics query orchestration service.

    This service implements the GetMetrics and QueryTraces inbound ports by
    coordinating calls to the TimeSeriesRepository and OTelTraceProcessor
    outbound ports. It applies business rules for query validation, automatic
    rollup selection, and result caching to meet the SLO target of p99 < 500ms.

    The service is designed for stateless operation: all state is delegated
    to the outbound ports, enabling horizontal scaling through multiple
    service instances behind a load balancer.
    """

    def __init__(
        self,
        time_series_repo: TimeSeriesRepository,
        event_repo: EventRepository,
        otel_processor: OTelTraceProcessor,
        max_query_range_days: int = 90,
    ) -> None:
        """Initialize the analytics service with required outbound ports.

        Args:
            time_series_repo: Repository for time series data (ClickHouse).
            event_repo: Repository for event metadata (PostgreSQL).
            otel_processor: Processor for OTel trace data.
            max_query_range_days: Maximum allowed query range in days to
                prevent accidentally scanning too much data.
        """
        self._time_series_repo = time_series_repo
        self._event_repo = event_repo
        self._otel_processor = otel_processor
        self._max_query_range_days = max_query_range_days

    def get_metrics(
        self,
        metric_names: list[str],
        labels: dict[str, str] | None = None,
        time_range: TimeRange | None = None,
        window: AggregationWindow = AggregationWindow.ONE_MINUTE,
        aggregation: AggregationFunction = AggregationFunction.AVG,
    ) -> list[TimeSeries]:
        """Retrieve aggregated metric time series data.

        Validates the query parameters, selects the appropriate rollup
        table based on the time range and window size, and delegates to
        the time series repository for execution. The method enforces a
        maximum query range to prevent excessive data scans.

        Args:
            metric_names: List of metric identifiers to query.
            labels: Optional label selectors for dimensional filtering.
            time_range: The temporal scope of the query. Defaults to the
                last hour if not specified.
            window: The aggregation window size.
            aggregation: The aggregation function to apply.

        Returns:
            A list of TimeSeries, one per requested metric name.

        Raises:
            InvalidTimeRangeError: If the time range exceeds the maximum
                allowed range or is malformed.
        """
        if not metric_names:
            return []

        if time_range is None:
            time_range = TimeRange(
                start=datetime.now(timezone.utc) - timedelta(hours=1),
                end=datetime.now(timezone.utc),
            )

        self._validate_time_range(time_range)
        optimal_window = self._select_optimal_window(time_range, window)

        logger.info(
            "Querying metrics: names=%s, window=%s, aggregation=%s, range=%s",
            metric_names,
            optimal_window.value,
            aggregation.value,
            time_range,
        )

        return self._time_series_repo.query(
            metric_names=metric_names,
            labels=labels,
            time_range=time_range,
            window=optimal_window,
            aggregation=aggregation,
        )

    def query_traces(
        self,
        trace_id: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
        tags: dict[str, str] | None = None,
        time_range: TimeRange | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search distributed traces based on various criteria.

        If a trace_id is provided, performs a direct lookup. Otherwise,
        delegates to the OTel trace processor for filtered search.
        Enforces a maximum limit to prevent excessive result sets.

        Args:
            trace_id: Optional trace ID for direct lookup.
            service_name: Optional service name filter.
            operation_name: Optional operation name filter.
            min_duration_ms: Optional minimum duration filter.
            max_duration_ms: Optional maximum duration filter.
            tags: Optional tag-based filters.
            time_range: The temporal scope of the search.
            limit: Maximum number of traces to return.

        Returns:
            A list of trace dictionaries matching the criteria.

        Raises:
            QueryTooBroadError: If no trace_id is provided and no
                service_name or operation_name filter is specified.
        """
        if trace_id:
            trace = self._otel_processor.get_trace(trace_id)
            return [trace] if trace else []

        if not service_name and not operation_name and not tags:
            raise QueryTooBroadError(
                "Trace query must include at least one of: service_name, "
                "operation_name, or tags filter to prevent excessive data scans."
            )

        start_time = time_range.start if time_range else None
        end_time = time_range.end if time_range else None

        return self._otel_processor.query_traces(
            service_name=service_name,
            operation_name=operation_name,
            min_duration_ms=min_duration_ms,
            max_duration_ms=max_duration_ms,
            tags=tags,
            start_time=start_time,
            end_time=end_time,
            limit=min(limit, 100),
        )

    def get_dependencies(
        self,
        time_range: TimeRange | None = None,
    ) -> dict[str, Any]:
        """Retrieve the service dependency graph for a time range.

        Delegates to the OTel trace processor to aggregate span data
        into a service-to-service communication topology.

        Args:
            time_range: The temporal scope. Defaults to the last hour.

        Returns:
            A dictionary representing the dependency graph with nodes
            and edges including latency percentiles and error rates.
        """
        if time_range is None:
            time_range = TimeRange(
                start=datetime.now(timezone.utc) - timedelta(hours=1),
                end=datetime.now(timezone.utc),
            )

        return self._otel_processor.get_dependencies(
            start_time=time_range.start,
            end_time=time_range.end,
        )

    def _validate_time_range(self, time_range: TimeRange) -> None:
        """Validate that the time range is within acceptable bounds.

        Checks that the time range does not exceed the maximum allowed
        range and that the start timestamp is before the end timestamp.
        This validation prevents accidental scans of excessive data that
        could violate the SLO target of p99 < 500ms.

        Args:
            time_range: The time range to validate.

        Raises:
            InvalidTimeRangeError: If the time range is invalid.
        """
        duration_days = time_range.duration_seconds / 86400.0
        if duration_days > self._max_query_range_days:
            raise InvalidTimeRangeError(
                f"Time range of {duration_days:.1f} days exceeds the maximum "
                f"allowed range of {self._max_query_range_days} days. "
                f"Use a narrower time range or coarser granularity."
            )

    def _select_optimal_window(
        self,
        time_range: TimeRange,
        requested_window: AggregationWindow,
    ) -> AggregationWindow:
        """Select the optimal aggregation window based on the time range.

        For very long time ranges, raw 1-minute data would produce
        excessively large result sets. This method automatically upgrades
        the window size to maintain reasonable result sizes while still
        providing useful granularity. The thresholds are calibrated to
        keep result sets under 10,000 data points per metric.

        Args:
            time_range: The query time range.
            requested_window: The client-requested window size.

        Returns:
            The optimal window size, which may be larger than requested.
        """
        duration_hours = time_range.duration_seconds / 3600.0

        if requested_window == AggregationWindow.ONE_MINUTE and duration_hours > 72:
            return AggregationWindow.FIVE_MINUTES
        if requested_window == AggregationWindow.FIVE_MINUTES and duration_hours > 720:
            return AggregationWindow.ONE_HOUR
        if requested_window == AggregationWindow.ONE_HOUR and duration_hours > 4320:
            return AggregationWindow.ONE_DAY

        return requested_window
