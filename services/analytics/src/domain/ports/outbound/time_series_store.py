"""
Time series storage port for the Analytics service.

This module defines the TimeSeriesRepository protocol, which is the outbound
port for all interactions with the time series database (ClickHouse). The
protocol specifies operations for writing metric data points, querying time
series with aggregation, creating pre-aggregated rollup tables, and managing
data retention policies.

ClickHouse was chosen for its exceptional query performance on time series
aggregations, supporting billions of data points with sub-second query
latency. The repository uses ClickHouse's MergeTree engine for raw metric
data and Materialized Views for automatic rollup aggregation. Data points
are written in batches using the ClickHouse HTTP INSERT protocol for maximum
throughput, and queries leverage the query cache and optimized aggregation
functions.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ...models.aggregation import AggregationFunction, AggregationWindow, AggregatedDataPoint
from ...models.metric import DataPoint, TimeSeries
from ...models.report import TimeRange


@runtime_checkable
class TimeSeriesRepository(Protocol):
    """Outbound port for time series database interactions.

    This protocol defines the contract between the domain services and the
    ClickHouse time series store. All metric writes go through this interface,
    enabling the domain layer to remain ignorant of the specific database
    technology, query syntax, or connection management details. Adapters
    implementing this port handle batching, retry logic, and schema management.
    """

    def write(self, series: list[DataPoint], metric_name: str, labels: dict[str, str]) -> None:
        """Write a batch of metric data points to the time series database.

        Data points are written in batches of up to 10,000 using the ClickHouse
        HTTP INSERT protocol for maximum throughput. The metric name and labels
        are stored alongside each data point to enable dimensional queries.

        Args:
            series: List of DataPoint objects to persist.
            metric_name: The name of the metric these data points belong to.
            labels: Dimensional labels for filtering and grouping.

        Raises:
            StorageWriteError: If the write operation fails after retries.
        """
        ...

    def query(
        self,
        metric_names: list[str],
        labels: dict[str, str] | None,
        time_range: TimeRange,
        window: AggregationWindow,
        aggregation: AggregationFunction,
    ) -> list[TimeSeries]:
        """Execute a time series query with aggregation.

        Queries the time series database with the specified filters and
        aggregation parameters. When the requested time range exceeds raw
        data retention, automatically falls back to pre-aggregated rollup
        tables for performance.

        Args:
            metric_names: List of metric identifiers to query.
            labels: Optional label selectors for dimensional filtering.
            time_range: The temporal scope of the query.
            window: The aggregation window size for data point granularity.
            aggregation: The function used to combine data points.

        Returns:
            A list of TimeSeries, one per requested metric name.

        Raises:
            StorageQueryError: If the query execution fails.
        """
        ...

    def write_aggregated(self, points: list[AggregatedDataPoint], metric_name: str, labels: dict[str, str]) -> None:
        """Write pre-aggregated data points to the rollup table.

        Pre-computed rollups are written by the aggregation engine after
        processing raw data points. These rollups dramatically reduce query
        latency for dashboard refreshes by eliminating the need to scan
        raw data for common time ranges.

        Args:
            points: List of AggregatedDataPoint objects to persist.
            metric_name: The name of the metric these rollups belong to.
            labels: Dimensional labels matching the original metric.

        Raises:
            StorageWriteError: If the write operation fails after retries.
        """
        ...

    def create_rollup(self, metric_name: str, interval: AggregationWindow) -> None:
        """Create a pre-aggregated rollup configuration for a metric.

        Rollups are implemented as ClickHouse Materialized Views that
        automatically aggregate raw data as it is inserted. This method
        creates the necessary view definition and retention policy.

        Args:
            metric_name: The metric to create a rollup for.
            interval: The aggregation interval for the rollup table.

        Raises:
            RollupCreationError: If the rollup cannot be created.
        """
        ...

    def get_retention_policies(self) -> list[dict]:
        """Retrieve current data retention policies.

        Returns the retention configuration for each aggregation tier,
        including the retention period and the storage path. This
        information is used by the report service to determine data
        availability for a given time range.

        Returns:
            A list of dictionaries, each containing the retention policy
            details for a specific aggregation tier.
        """
        ...
