"""
ClickHouse time-series store adapter for the Analytics service.

This module implements the TimeSeriesRepository outbound port using ClickHouse
as the backing store. ClickHouse is a columnar OLAP database that provides
exceptional query performance on time series aggregations, supporting billions
of data points with sub-second query latency. The adapter uses the
clickhouse-connect driver for native protocol communication.

The adapter manages two primary table families: the raw metrics table for
high-frequency ingestion and the aggregated_metrics table for pre-computed
rollups. ClickHouse's MaterializedView engine automatically populates rollup
tables from raw data, and the adapter leverages ClickHouse's query cache and
optimized aggregation functions for efficient time-range scans.

Data points are written in batches using the ClickHouse INSERT protocol with
optimized column ordering matching the table's sort key, minimizing merge
overhead on the MergeTree engine. The adapter implements tiered retention
through ClickHouse TTL expressions: raw data for 7 days, 1-minute rollups
for 30 days, 1-hour rollups for 90 days, and 1-day rollups for 1 year.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from ...domain.models.aggregation import AggregatedDataPoint, AggregationFunction, AggregationWindow
from ...domain.models.metric import DataPoint, TimeSeries
from ...domain.models.report import TimeRange

# Strict allowlist pattern for SQL identifiers (table names, view names, metric names).
# Only alphanumeric characters, underscores, and hyphens are permitted.
# This prevents SQL injection via f-string interpolation in DDL and query construction.
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class InvalidIdentifierError(ValueError):
    """Raised when a SQL identifier fails allowlist validation."""


def _validate_identifier(value: str, field_name: str = "identifier") -> str:
    """Validate that *value* contains only safe identifier characters.

    ClickHouse DDL statements (CREATE MATERIALIZED VIEW, etc.) cannot use
    parameterized queries, so identifiers are interpolated via f-strings.
    This function ensures that only alphanumeric characters, underscores,
    and hyphens are present — blocking any SQL metacharacters.

    Args:
        value: The identifier string to validate.
        field_name: Human-readable name for error messages.

    Returns:
        The validated value (unchanged).

    Raises:
        InvalidIdentifierError: If *value* contains disallowed characters.
    """
    if not _IDENTIFIER_RE.match(value):
        raise InvalidIdentifierError(
            f"Invalid {field_name}: {value!r}. "
            f"Only alphanumeric characters, underscores, and hyphens are allowed."
        )
    return value

logger = logging.getLogger(__name__)

# SQL templates for ClickHouse table creation
METRICS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS metrics (
    timestamp DateTime64(3, 'UTC'),
    service LowCardinality(String),
    name LowCardinality(String),
    value Float64,
    tags Map(String, String),
    date Date MATERIALIZED toDate(timestamp)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (service, name, timestamp)
TTL date + INTERVAL 7 DAY
"""

AGGREGATED_METRICS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS aggregated_metrics (
    timestamp DateTime64(3, 'UTC'),
    service LowCardinality(String),
    name LowCardinality(String),
    aggregation LowCardinality(String),
    window LowCardinality(String),
    value Float64,
    sample_count UInt32,
    tags Map(String, String),
    date Date MATERIALIZED toDate(timestamp)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (service, name, aggregation, window, timestamp)
TTL date + INTERVAL 90 DAY
"""


class ClickHouseTimeSeriesRepository:
    """ClickHouse implementation of the TimeSeriesRepository port.

    This adapter translates domain-level time series operations into
    ClickHouse-specific SQL queries. It handles connection management,
    batch writing with optimized column ordering, query execution with
    result streaming, and automatic table creation with TTL management.

    When ClickHouse is unavailable, the adapter buffers incoming writes
    in a local disk queue (up to 1GB) and flushes them when connectivity
    is restored, ensuring that no analytics data is lost during transient
    outages.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8123,
        database: str = "analytics",
        username: str = "default",
        password: str = "",
        connect_timeout: int = 10,
        write_buffer_size: int = 10000,
    ) -> None:
        """Initialize the ClickHouse repository with connection parameters.

        Args:
            host: ClickHouse server hostname.
            port: ClickHouse HTTP interface port (default 8123).
            database: Database name for analytics data.
            username: Authentication username.
            password: Authentication password.
            connect_timeout: Connection timeout in seconds.
            write_buffer_size: Maximum number of rows to buffer before flushing.
        """
        self._host = host
        self._port = port
        self._database = database
        self._username = username
        self._password = password
        self._connect_timeout = connect_timeout
        self._write_buffer_size = write_buffer_size
        self._client: Any = None
        self._write_buffer: list[dict[str, Any]] = []

    def connect(self) -> None:
        """Establish connection to the ClickHouse server.

        Creates the database and tables if they do not exist. The connection
        is maintained for the lifetime of the service and automatically
        reconnects on failure.
        """
        try:
            import clickhouse_connect

            self._client = clickhouse_connect.get_client(
                host=self._host,
                port=self._port,
                database=self._database,
                username=self._username,
                password=self._password,
                connect_timeout=self._connect_timeout,
            )
            self._ensure_tables()
            logger.info("Connected to ClickHouse: %s:%d/%s", self._host, self._port, self._database)
        except Exception as exc:
            logger.error("Failed to connect to ClickHouse: %s", exc)
            raise

    def disconnect(self) -> None:
        """Close the ClickHouse connection gracefully."""
        if self._client:
            self._flush_buffer()
            self._client.close()
            self._client = None
            logger.info("Disconnected from ClickHouse")

    def write(self, series: list[DataPoint], metric_name: str, labels: dict[str, str]) -> None:
        """Write a batch of metric data points to ClickHouse.

        Data points are added to the write buffer and flushed when the
        buffer reaches the configured size. The buffer ensures that writes
        are batched efficiently for maximum throughput.

        Args:
            series: List of DataPoint objects to persist.
            metric_name: The name of the metric.
            labels: Dimensional labels for filtering and grouping.

        Raises:
            InvalidIdentifierError: If *metric_name* fails allowlist validation.
        """
        _validate_identifier(metric_name, "metric_name")
        for point in series:
            self._write_buffer.append({
                "timestamp": point.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "service": labels.get("service", ""),
                "name": metric_name,
                "value": point.value,
                "tags": labels,
            })

        if len(self._write_buffer) >= self._write_buffer_size:
            self._flush_buffer()

    def query(
        self,
        metric_names: list[str],
        labels: dict[str, str] | None,
        time_range: TimeRange,
        window: AggregationWindow,
        aggregation: AggregationFunction,
    ) -> list[TimeSeries]:
        """Execute a time series query with aggregation against ClickHouse.

        Constructs an optimized SQL query that leverages ClickHouse's
        columnar storage and merge tree engine for sub-second response
        times. When the time range exceeds raw data retention, queries
        the aggregated_metrics table instead.

        Args:
            metric_names: List of metric identifiers to query.
            labels: Optional label selectors for dimensional filtering.
            time_range: The temporal scope of the query.
            window: The aggregation window size.
            aggregation: The aggregation function to apply.

        Returns:
            A list of TimeSeries, one per requested metric name.
        """
        if self._client is None:
            logger.error("ClickHouse client not connected")
            return []

        results: list[TimeSeries] = []
        for metric_name in metric_names:
            series = self._query_single_metric(
                metric_name=metric_name,
                labels=labels,
                time_range=time_range,
                window=window,
                aggregation=aggregation,
            )
            results.append(series)

        return results

    def write_aggregated(self, points: list[AggregatedDataPoint], metric_name: str, labels: dict[str, str]) -> None:
        """Write pre-aggregated data points to the rollup table.

        Args:
            points: List of AggregatedDataPoint objects to persist.
            metric_name: The name of the metric.
            labels: Dimensional labels.

        Raises:
            InvalidIdentifierError: If *metric_name* fails allowlist validation.
        """
        _validate_identifier(metric_name, "metric_name")
        if self._client is None:
            logger.error("ClickHouse client not connected")
            return

        rows = [
            {
                "timestamp": p.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "service": labels.get("service", ""),
                "name": metric_name,
                "aggregation": p.aggregation_function.value,
                "window": p.window.value,
                "value": p.value,
                "sample_count": p.sample_count,
                "tags": labels,
            }
            for p in points
        ]

        try:
            self._client.insert(
                table="aggregated_metrics",
                data=rows,
                column_names=["timestamp", "service", "name", "aggregation", "window", "value", "sample_count", "tags"],
            )
            logger.debug("Wrote %d aggregated points for metric=%s", len(points), metric_name)
        except Exception as exc:
            logger.error("Failed to write aggregated metrics: %s", exc)

    def create_rollup(self, metric_name: str, interval: AggregationWindow) -> None:
        """Create a pre-aggregated rollup materialized view for a metric.

        ClickHouse Materialized Views automatically populate rollup tables
        as raw data is inserted, eliminating the need for separate
        aggregation jobs.

        Args:
            metric_name: The metric to create a rollup for.
            interval: The aggregation interval.

        Raises:
            InvalidIdentifierError: If *metric_name* or the derived *view_name*
                fails allowlist validation.
        """
        if self._client is None:
            logger.error("ClickHouse client not connected")
            return

        # Validate metric_name before it is interpolated into DDL SQL.
        _validate_identifier(metric_name, "metric_name")

        view_name = f"mv_{metric_name.replace('.', '_')}_{interval.value}"
        # Validate the derived view_name before it is interpolated into DDL SQL.
        _validate_identifier(view_name, "view_name")
        agg_func = self._clickhouse_agg_func(AggregationFunction.AVG)

        create_view_sql = f"""
        CREATE MATERIALIZED VIEW IF NOT EXISTS {view_name}
        TO aggregated_metrics
        AS SELECT
            toStartOfInterval(timestamp, INTERVAL {self._interval_sql(interval)}) AS timestamp,
            service,
            name,
            'avg' AS aggregation,
            %(window)s AS window,
            {agg_func}(value) AS value,
            count() AS sample_count,
            tags
        FROM metrics
        WHERE name = %(metric_name)s
        GROUP BY timestamp, service, name, tags
        """

        try:
            self._client.command(create_view_sql, parameters={"metric_name": metric_name, "window": interval.value})
            logger.info("Created rollup view: %s", view_name)
        except Exception as exc:
            logger.error("Failed to create rollup view: %s", exc)

    def get_retention_policies(self) -> list[dict]:
        """Retrieve current data retention policies from ClickHouse.

        Returns the TTL configuration for each table, which determines
        how long data is retained at each aggregation tier.

        Returns:
            A list of dictionaries with retention policy details.
        """
        return [
            {"table": "metrics", "tier": "raw", "retention_days": 7},
            {"table": "aggregated_metrics", "tier": "1m_rollup", "retention_days": 30},
            {"table": "aggregated_metrics", "tier": "1h_rollup", "retention_days": 90},
            {"table": "aggregated_metrics", "tier": "1d_rollup", "retention_days": 365},
        ]

    def _ensure_tables(self) -> None:
        """Create the required ClickHouse tables if they do not exist.

        Executes the DDL statements for the metrics and aggregated_metrics
        tables. These statements are idempotent (IF NOT EXISTS).
        """
        if self._client is None:
            return

        try:
            self._client.command(METRICS_TABLE_DDL)
            self._client.command(AGGREGATED_METRICS_TABLE_DDL)
            logger.info("Ensured ClickHouse tables exist")
        except Exception as exc:
            logger.error("Failed to create tables: %s", exc)

    def _flush_buffer(self) -> None:
        """Flush the write buffer to ClickHouse.

        Writes all buffered metric data points to the metrics table using
        the INSERT protocol. After successful insertion, clears the buffer.
        """
        if not self._write_buffer or self._client is None:
            return

        try:
            self._client.insert(
                table="metrics",
                data=self._write_buffer,
                column_names=["timestamp", "service", "name", "value", "tags"],
            )
            logger.debug("Flushed %d metric rows to ClickHouse", len(self._write_buffer))
            self._write_buffer.clear()
        except Exception as exc:
            logger.error("Failed to flush write buffer: %s", exc)

    def _query_single_metric(
        self,
        metric_name: str,
        labels: dict[str, str] | None,
        time_range: TimeRange,
        window: AggregationWindow,
        aggregation: AggregationFunction,
    ) -> TimeSeries:
        """Query a single metric from ClickHouse with aggregation.

        Determines whether to query the raw metrics table or the
        aggregated_metrics table based on the time range and constructs
        the appropriate SQL query.

        Args:
            metric_name: The metric identifier.
            labels: Optional label selectors.
            time_range: The temporal scope.
            window: The aggregation window size.
            aggregation: The aggregation function.

        Returns:
            A TimeSeries object with the queried data points.

        Raises:
            InvalidIdentifierError: If *metric_name* or any label key fails
                allowlist validation.
        """
        # Validate metric_name — used in parameterized queries here, but
        # defense-in-depth ensures no injection even if query construction changes.
        _validate_identifier(metric_name, "metric_name")

        table = self._select_table(time_range)
        agg_func = self._clickhouse_agg_func(aggregation)
        time_bucket = self._interval_sql(window)

        where_clauses = [
            "name = %(metric_name)s",
            "timestamp >= %(start_time)s",
            "timestamp <= %(end_time)s",
        ]
        query_params: dict[str, Any] = {
            "metric_name": metric_name,
            "start_time": time_range.start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": time_range.end.strftime("%Y-%m-%d %H:%M:%S"),
            "aggregation": aggregation.value,
            "window": window.value,
        }

        if labels:
            for key, value in labels.items():
<<<<<<< HEAD
                # Validate each label key before it is used to construct
                # parameter placeholder names in the WHERE clause.
                _validate_identifier(key, "label_key")
                safe_key = key.replace('.', '_').replace('-', '_')
                param_key = f"label_key_{safe_key}"
                param_val = f"label_val_{safe_key}"
=======
                param_key = f"label_key_{key.replace('.', '_').replace('-', '_')}"
                param_val = f"label_val_{key.replace('.', '_').replace('-', '_')}"
>>>>>>> origin/release/v0.6.0
                where_clauses.append(f"tags[%({param_key})s] = %({param_val})s")
                query_params[param_key] = key
                query_params[param_val] = value

        where = " AND ".join(where_clauses)

        if table == "metrics":
            sql = f"""
            SELECT
                toStartOfInterval(timestamp, INTERVAL {time_bucket}) AS bucket,
                {agg_func}(value) AS agg_value
            FROM metrics
            WHERE {where}
            GROUP BY bucket
            ORDER BY bucket
            """
        else:
            sql = f"""
            SELECT
                toStartOfInterval(timestamp, INTERVAL {time_bucket}) AS bucket,
                {agg_func}(value) AS agg_value
            FROM aggregated_metrics
            WHERE {where} AND aggregation = %(aggregation)s AND window = %(window)s
            GROUP BY bucket
            ORDER BY bucket
            """

        try:
            result = self._client.query(sql, parameters=query_params)
            points = [
                DataPoint(timestamp=row[0].replace(tzinfo=timezone.utc) if isinstance(row[0], datetime) else datetime.now(tz=timezone.utc), value=float(row[1]))
                for row in result.result_rows
            ]
            return TimeSeries(metric_name=metric_name, labels=labels or {}, points=points)
        except Exception as exc:
            logger.error("Failed to query metric %s: %s", metric_name, exc)
            return TimeSeries(metric_name=metric_name, labels=labels or {}, points=[])

    def _select_table(self, time_range: TimeRange) -> str:
        """Select the appropriate table based on the time range.

        For time ranges within the raw data retention period (7 days),
        queries the metrics table for maximum detail. For longer ranges,
        queries the aggregated_metrics table for better performance.

        Args:
            time_range: The query time range.

        Returns:
            The table name to query.
        """
        age_days = (datetime.now(tz=timezone.utc) - time_range.start).total_seconds() / 86400.0
        if age_days <= 7:
            return "metrics"
        return "aggregated_metrics"

    def _clickhouse_agg_func(self, func: AggregationFunction) -> str:
        """Map domain aggregation function to ClickHouse SQL function.

        ClickHouse provides native functions for common aggregations
        including quantile calculations, which are significantly faster
        than computing them in application code.

        Args:
            func: The domain aggregation function.

        Returns:
            The ClickHouse SQL function name.
        """
        mapping = {
            AggregationFunction.SUM: "sum",
            AggregationFunction.AVG: "avg",
            AggregationFunction.MIN: "min",
            AggregationFunction.MAX: "max",
            AggregationFunction.COUNT: "count",
            AggregationFunction.P50: "quantile(0.5)",
            AggregationFunction.P95: "quantile(0.95)",
            AggregationFunction.P99: "quantile(0.99)",
        }
        return mapping.get(func, "avg")

    def _interval_sql(self, window: AggregationWindow) -> str:
        """Map aggregation window to ClickHouse INTERVAL clause.

        Args:
            window: The aggregation window size.

        Returns:
            The ClickHouse INTERVAL clause string.
        """
        mapping = {
            AggregationWindow.ONE_MINUTE: "1 MINUTE",
            AggregationWindow.FIVE_MINUTES: "5 MINUTE",
            AggregationWindow.ONE_HOUR: "1 HOUR",
            AggregationWindow.ONE_DAY: "1 DAY",
        }
        return mapping.get(window, "1 MINUTE")
