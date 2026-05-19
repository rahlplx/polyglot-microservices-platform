"""
Outbound adapters for the Analytics service.

Implements ClickHouse time-series storage, PostgreSQL event/metadata storage,
OTel span processing, and self-instrumentation. Each adapter translates
between domain types and infrastructure-specific APIs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from ..domain.models import (
    AggregationFunction, Dashboard, DataPoint, Granularity, TimeSeries,
)
from ..domain.ports import (
    DashboardRepositoryPort, EventRepositoryPort, TimeSeriesRepositoryPort,
)

logger = logging.getLogger(__name__)


class ClickHouseTimeSeriesRepo(TimeSeriesRepositoryPort):
    """ClickHouse-based time-series storage implementation.
    ClickHouse provides columnar storage that is highly efficient for
    time-series data, supporting fast range queries and aggregations.
    This adapter handles schema creation, data ingestion, and query
    translation between the domain model and ClickHouse SQL.
    For development, an in-memory fallback is provided."""

    def __init__(self, dsn: str = "") -> None:
        self._dsn = dsn
        self._data_points: list[dict[str, Any]] = []
        # In production: client = clickhouse_connect.get_client(dsn=dsn)

    async def write_data_point(
        self, metric_name: str, service: str, timestamp: str, value: float, tags: dict[str, str],
    ) -> None:
        """Write a single data point to ClickHouse.
        In production, uses batch INSERT for optimal write throughput."""
        self._data_points.append({
            "metric_name": metric_name,
            "service": service,
            "timestamp": timestamp,
            "value": value,
            "tags": tags,
        })

    async def query_time_series(
        self,
        metric_name: str,
        service: Optional[str],
        tags: Optional[dict[str, str]],
        aggregation: AggregationFunction,
        granularity: Granularity,
        start_time: str,
        end_time: str,
    ) -> TimeSeries:
        """Query aggregated time-series data from ClickHouse.
        Translates the domain query into a ClickHouse SQL aggregation query
        with the appropriate time bucketing and filtering."""
        # In production:
        # SELECT
        #   toStartOfInterval(timestamp, INTERVAL {granularity}) AS bucket,
        #   {aggregation_func}(value) AS agg_value
        # FROM metrics
        # WHERE metric_name = {metric_name} AND timestamp BETWEEN {start} AND {end}
        # GROUP BY bucket ORDER BY bucket

        # Filter in-memory data for development.
        filtered = [
            dp for dp in self._data_points
            if dp["metric_name"] == metric_name
            and (service is None or dp["service"] == service)
        ]

        points = [
            DataPoint(
                timestamp=datetime.fromisoformat(dp["timestamp"]) if isinstance(dp["timestamp"], str) else dp["timestamp"],
                value=dp["value"],
                tags=dp.get("tags", {}),
            )
            for dp in filtered
        ]

        return TimeSeries(
            metric_name=metric_name,
            service=service or "",
            aggregation=aggregation,
            granularity=granularity,
            points=points,
        )


class PostgresEventRepo(EventRepositoryPort):
    """PostgreSQL-based raw event storage.
    Stores business events for audit, replay, and historical analysis.
    Uses SQLAlchemy async for non-blocking database operations."""

    def __init__(self, dsn: str = "") -> None:
        self._dsn = dsn
        self._events: list[dict[str, Any]] = []

    async def save_event(self, event_type: str, source: str, payload: dict[str, Any]) -> str:
        """Persist a raw business event to PostgreSQL."""
        event_id = f"evt_{len(self._events)}_{datetime.now(timezone.utc).timestamp()}"
        self._events.append({
            "id": event_id,
            "event_type": event_type,
            "source": source,
            "payload": payload,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return event_id

    async def get_events(
        self,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query stored events with flexible filtering."""
        filtered = self._events
        if event_type:
            filtered = [e for e in filtered if e["event_type"] == event_type]
        if source:
            filtered = [e for e in filtered if e["source"] == source]
        return filtered[:limit]


class PostgresDashboardRepo(DashboardRepositoryPort):
    """PostgreSQL-based dashboard configuration storage."""

    def __init__(self) -> None:
        self._dashboards: dict[str, Dashboard] = {}

    async def save(self, dashboard: Dashboard) -> Dashboard:
        self._dashboards[dashboard.id] = dashboard
        return dashboard

    async def get_by_id(self, dashboard_id: str) -> Optional[Dashboard]:
        return self._dashboards.get(dashboard_id)

    async def list_by_owner(self, owner: Optional[str] = None) -> list[Dashboard]:
        if owner:
            return [d for d in self._dashboards.values() if d.owner == owner]
        return list(self._dashboards.values())


class OtelSpanProcessor:
    """Custom OTel span processor for extracting service metrics from traces.
    This processor hooks into the OTel SDK pipeline, processing each completed
    span to extract latency, error rate, and throughput metrics. The extracted
    metrics are written to ClickHouse for dashboard visualization. This provides
    zero-code observability for all instrumented services in the platform."""

    def __init__(self, time_series_repo: TimeSeriesRepositoryPort) -> None:
        self._ts_repo = time_series_repo

    def on_start(self, parent_context: Any, span: Any) -> None:
        """Called when a span starts. No action needed for metrics extraction."""
        pass

    def on_end(self, span: Any) -> None:
        """Called when a span ends. Extract metrics from the completed span
        and write them to the time-series store for aggregation."""
        # In production: extract span attributes, write latency/error metrics.
        pass

    def shutdown(self) -> None:
        """Clean up resources."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> None:
        """Force flush any buffered spans."""
        pass
