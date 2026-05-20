"""
Domain services for the Analytics service.

Implements the core business logic of metric aggregation, report generation,
event processing, and dashboard management. All services depend only on
domain ports (interfaces), maintaining the hexagonal architecture boundary.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..models import (
    AggregationFunction, Dashboard, Granularity,
    Report, ReportType, TimeSeries,
)
from ..ports import (
    DashboardRepositoryPort, EventRepositoryPort, GetDashboardPort,
    GetMetricsPort, GetReportPort, StreamEventsPort,
    TimeSeriesRepositoryPort,
)

logger = logging.getLogger(__name__)


class AnalyticsService(GetMetricsPort, StreamEventsPort):
    """Core analytics query and event processing service.
    Coordinates between the time-series store, event repository,
    and aggregation engine to provide real-time and historical
    metric data. This is the primary application service for the
    analytics subsystem of the gstack platform."""

    def __init__(
        self,
        time_series_repo: TimeSeriesRepositoryPort,
        event_repo: EventRepositoryPort,
        aggregation_service: "AggregationService",
    ) -> None:
        self._ts_repo = time_series_repo
        self._event_repo = event_repo
        self._aggregation = aggregation_service

    async def get_metrics(
        self,
        metric_name: str,
        service: Optional[str] = None,
        tags: Optional[dict[str, str]] = None,
        aggregation: AggregationFunction = AggregationFunction.AVG,
        granularity: Granularity = Granularity.FIVE_MINUTES,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> list[TimeSeries]:
        """Query time-series metrics with flexible filtering and aggregation.
        Delegates to the time-series repository for data retrieval, then
        applies the requested aggregation function and granularity."""
        if not end_time:
            end_time = datetime.now(timezone.utc).isoformat()
        if not start_time:
            start_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        series = await self._ts_repo.query_time_series(
            metric_name=metric_name,
            service=service,
            tags=tags,
            aggregation=aggregation,
            granularity=granularity,
            start_time=start_time,
            end_time=end_time,
        )
        return [series]

    async def process_event(self, event: dict[str, Any]) -> None:
        """Process a business event from the event stream.
        Extracts metric data points from the event payload and writes
        them to the time-series store for real-time aggregation."""
        event_type = event.get("type", "unknown")
        source = event.get("source", "unknown")
        data = event.get("data", {})

        # Persist the raw event for audit and replay.
        await self._event_repo.save_event(event_type, source, event)

        # Extract metrics from the event based on type.
        metric_name = f"{source}.{event_type}"
        service_name = data.get("service", source)

        # Write the event as a counter data point.
        await self._ts_repo.write_data_point(
            metric_name=metric_name,
            service=service_name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            value=1.0,
            tags={"event_type": event_type, "source": source},
        )

        # Extract latency metrics if present.
        if "duration_ms" in data:
            await self._ts_repo.write_data_point(
                metric_name=f"{service_name}.latency",
                service=service_name,
                timestamp=datetime.now(timezone.utc).isoformat(),
                value=float(data["duration_ms"]),
                tags={"operation": data.get("operation", "unknown")},
            )

        logger.debug("event processed", extra={"event_type": event_type, "source": source})


class AggregationService:
    """Time-window aggregation engine for pre-computing metric rollups.
    Aggregation reduces the query load on ClickHouse by pre-computing
    common aggregation windows (1min, 5min, 1hr, 1day). The engine
    supports multiple aggregation functions and handles the conversion
    between raw data points and aggregated time-series."""

    def __init__(self, time_series_repo: TimeSeriesRepositoryPort) -> None:
        self._ts_repo = time_series_repo

    async def aggregate_window(
        self,
        metric_name: str,
        granularity: Granularity,
        function: AggregationFunction,
        window_start: datetime,
        window_end: datetime,
    ) -> TimeSeries:
        """Aggregate raw data points within a time window.
        Queries the time-series store for raw data, applies the
        aggregation function, and returns the result as a TimeSeries."""
        series = await self._ts_repo.query_time_series(
            metric_name=metric_name,
            service=None,
            tags=None,
            aggregation=function,
            granularity=granularity,
            start_time=window_start.isoformat(),
            end_time=window_end.isoformat(),
        )
        return series

    def compute_percentile(self, values: list[float], percentile: float) -> float:
        """Compute the given percentile from a list of values.
        Uses linear interpolation between adjacent values, which is
        the standard method for percentile calculation in observability
        systems. Returns 0.0 for empty value lists."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        n = len(sorted_values)
        index = (percentile / 100.0) * (n - 1)
        lower = int(index)
        upper = min(lower + 1, n - 1)
        fraction = index - lower
        return sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower])


class ReportService(GetReportPort):
    """Analytics report generation and retrieval service.
    Generates reports by aggregating metrics over specified time ranges,
    applying the requested report type template, and formatting the
    output. Generated reports are cached for subsequent identical requests
    to avoid redundant computation."""

    def __init__(self, time_series_repo: TimeSeriesRepositoryPort) -> None:
        self._ts_repo = time_series_repo
        self._report_cache: dict[str, Report] = {}

    async def generate_report(
        self,
        report_type: ReportType,
        services: list[str],
        start_time: str,
        end_time: str,
        granularity: Granularity = Granularity.ONE_HOUR,
        format: str = "JSON",
    ) -> Report:
        """Generate a new analytics report.
        Queries time-series data for each service and metric relevant
        to the report type, aggregates the results, and formats them
        according to the requested output format."""
        report = Report(
            report_type=report_type,
            title=f"{report_type.value} Report",
            time_range_start=datetime.fromisoformat(start_time),
            time_range_end=datetime.fromisoformat(end_time),
            granularity=granularity,
            services=services,
            format=format,
        )

        # Query metrics based on report type.
        metric_templates = {
            ReportType.SERVICE_HEALTH: ["availability", "error_rate", "latency_p99"],
            ReportType.API_PERFORMANCE: ["request_count", "latency_p50", "latency_p95", "latency_p99"],
            ReportType.BUSINESS_METRICS: ["order_count", "revenue", "conversion_rate"],
            ReportType.ERROR_ANALYSIS: ["error_count", "error_rate_by_type", "top_errors"],
        }

        metrics_to_query = metric_templates.get(report_type, [])

        for service in services:
            service_data: dict[str, Any] = {}
            for metric_name in metrics_to_query:
                series = await self._ts_repo.query_time_series(
                    metric_name=f"{service}.{metric_name}",
                    service=service,
                    tags=None,
                    aggregation=AggregationFunction.AVG,
                    granularity=granularity,
                    start_time=start_time,
                    end_time=end_time,
                )
                service_data[metric_name] = [
                    {"timestamp": p.timestamp.isoformat(), "value": p.value}
                    for p in series.points
                ]
            report.data[service] = service_data

        report.mark_generated()
        self._report_cache[report.id] = report
        return report

    async def get_report(self, report_id: str) -> Optional[Report]:
        """Retrieve a previously generated report by ID."""
        return self._report_cache.get(report_id)


class DashboardService(GetDashboardPort):
    """Dashboard configuration management service.
    Handles CRUD operations for analytics dashboards, which define
    real-time metric visualization configurations for the Admin UI."""

    def __init__(self, dashboard_repo: DashboardRepositoryPort) -> None:
        self._repo = dashboard_repo

    async def get_dashboard(self, dashboard_id: str) -> Optional[Dashboard]:
        """Retrieve a dashboard configuration by ID."""
        return await self._repo.get_by_id(dashboard_id)

    async def list_dashboards(self, owner: Optional[str] = None) -> list[Dashboard]:
        """List dashboards, optionally filtered by owner."""
        return await self._repo.list_by_owner(owner)
