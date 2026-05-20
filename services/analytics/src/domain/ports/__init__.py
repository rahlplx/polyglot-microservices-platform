"""
Domain ports for the Analytics service.

Ports define the hexagonal architecture boundaries. Inbound ports are
use case interfaces called by driving adapters (gRPC, REST, Kafka).
Outbound ports are infrastructure interfaces implemented by driven
adapters (ClickHouse, PostgreSQL, OTel).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..models import (
    AggregationFunction, Dashboard, Granularity,
    Report, ReportType, TimeSeries,
)


# === Inbound Ports (Use Cases) ===

class GetMetricsPort(ABC):
    """Use case for querying time-series metrics.
    Supports querying by metric name, service, tags, time range,
    and aggregation function. Returns TimeSeries objects suitable
    for dashboard rendering and API responses."""

    @abstractmethod
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
        """Query time-series metrics with flexible filtering and aggregation."""
        ...


class GetReportPort(ABC):
    """Use case for generating and retrieving analytics reports.
    Reports aggregate metrics over specified time ranges with configurable
    granularity and output format. Generated reports are cached for
    subsequent identical requests."""

    @abstractmethod
    async def generate_report(
        self,
        report_type: ReportType,
        services: list[str],
        start_time: str,
        end_time: str,
        granularity: Granularity = Granularity.ONE_HOUR,
        format: str = "JSON",
    ) -> Report:
        """Generate a new analytics report."""
        ...

    @abstractmethod
    async def get_report(self, report_id: str) -> Optional[Report]:
        """Retrieve a previously generated report by ID."""
        ...


class StreamEventsPort(ABC):
    """Use case for consuming and processing business events.
    Events are consumed from Kafka topics, parsed, and routed to
    the appropriate metric aggregation pipeline for real-time processing."""

    @abstractmethod
    async def process_event(self, event: dict[str, Any]) -> None:
        """Process a single business event from the event stream."""
        ...


class GetDashboardPort(ABC):
    """Use case for managing analytics dashboards.
    Dashboards define real-time metric visualization configurations
    that are served to the Admin UI and Grafana via the API."""

    @abstractmethod
    async def get_dashboard(self, dashboard_id: str) -> Optional[Dashboard]:
        """Retrieve a dashboard configuration by ID."""
        ...

    @abstractmethod
    async def list_dashboards(self, owner: Optional[str] = None) -> list[Dashboard]:
        """List dashboards, optionally filtered by owner."""
        ...


# === Outbound Ports (Infrastructure Interfaces) ===

class TimeSeriesRepositoryPort(ABC):
    """Interface for time-series data storage (ClickHouse).
    Handles writing raw data points and querying aggregated time-series.
    ClickHouse is chosen for its columnar storage efficiency with
    time-series data and its ability to handle high write throughput."""

    @abstractmethod
    async def write_data_point(
        self,
        metric_name: str,
        service: str,
        timestamp: str,
        value: float,
        tags: dict[str, str],
    ) -> None:
        """Write a single data point to the time-series store."""
        ...

    @abstractmethod
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
        """Query aggregated time-series data."""
        ...

    async def write_batch(self, data_points: list[dict[str, Any]]) -> int:
        """Write a batch of data points for high-throughput ingestion.
        Returns the number of points successfully written."""
        count = 0
        for dp in data_points:
            await self.write_data_point(
                metric_name=dp["metric_name"],
                service=dp["service"],
                timestamp=dp["timestamp"],
                value=dp["value"],
                tags=dp.get("tags", {}),
            )
            count += 1
        return count


class EventRepositoryPort(ABC):
    """Interface for raw event storage (PostgreSQL).
    Stores business events for audit, replay, and historical analysis.
    Events are written before aggregation to ensure data durability."""

    @abstractmethod
    async def save_event(self, event_type: str, source: str, payload: dict[str, Any]) -> str:
        """Persist a raw business event."""
        ...

    @abstractmethod
    async def get_events(
        self,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query stored events with flexible filtering."""
        ...


class DashboardRepositoryPort(ABC):
    """Interface for dashboard configuration storage (PostgreSQL)."""

    @abstractmethod
    async def save(self, dashboard: Dashboard) -> Dashboard:
        """Persist a dashboard configuration."""
        ...

    @abstractmethod
    async def get_by_id(self, dashboard_id: str) -> Optional[Dashboard]:
        """Retrieve a dashboard by ID."""
        ...

    @abstractmethod
    async def list_by_owner(self, owner: Optional[str] = None) -> list[Dashboard]:
        """List dashboards filtered by owner."""
        ...
