"""
Metric domain model for the Analytics service.

This module defines the core metric entities used throughout the analytics
domain. Metrics represent measurable quantities that are tracked over time,
such as request counts, latency percentiles, error rates, and business KPIs.
Each metric has a type that determines how it should be aggregated and
interpreted: counters accumulate over time, gauges represent point-in-time
values, and histograms capture distribution information.

The TimeSeries and DataPoint models provide the temporal dimension for metrics,
enabling time-range queries and trend analysis. These models are deliberately
kept free of any serialization or storage concerns, as those responsibilities
belong to the adapter layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MetricType(Enum):
    """Classification of metric types based on their aggregation semantics.

    Counter metrics monotonically increase and represent cumulative totals
    such as request counts or bytes transferred. Gauge metrics represent
    point-in-time values that can increase or decrease, such as active
    connections or memory usage. Histogram metrics capture the distribution
    of observations, enabling percentile calculations and statistical
    analysis of latency or size distributions.
    """

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass(frozen=True)
class DataPoint:
    """A single timestamped measurement value.

    DataPoint is the fundamental unit of time series data, pairing a
    timestamp with a numeric value. The frozen dataclass ensures
    immutability, which is critical for maintaining data integrity in
    concurrent processing pipelines where multiple aggregation workers
    may read the same data point simultaneously.
    """

    timestamp: datetime
    value: float

    def to_dict(self) -> dict[str, Any]:
        """Convert the data point to a plain dictionary representation.

        This method provides a serialization-friendly format that adapters
        can use to transform domain data into wire formats such as JSON
        or Protobuf. The timestamp is represented as an ISO 8601 string.
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "value": self.value,
        }


@dataclass(frozen=True)
class TimeSeries:
    """An ordered sequence of data points for a named metric.

    A TimeSeries represents the evolution of a metric over time, identified
    by its metric name and optional label dimensions. Labels enable
    dimensional analysis: for example, a "request_duration" metric might
    have labels like {"service": "catalog", "endpoint": "/api/v1/products"}
    that allow filtering and grouping in queries. The data points are
    ordered by timestamp to support efficient time-range slicing.
    """

    metric_name: str
    labels: dict[str, str] = field(default_factory=dict)
    points: list[DataPoint] = field(default_factory=list)

    @property
    def start_time(self) -> datetime | None:
        """Return the earliest timestamp in the series, or None if empty.

        This property is useful for validating that a time series falls
        within the requested query range and for determining whether
        pre-aggregated rollups should be used instead of raw data.
        """
        return self.points[0].timestamp if self.points else None

    @property
    def end_time(self) -> datetime | None:
        """Return the latest timestamp in the series, or None if empty.

        This property supports time-range validation and helps the
        aggregation engine determine overlap between adjacent windows.
        """
        return self.points[-1].timestamp if self.points else None

    @property
    def total_points(self) -> int:
        """Return the count of data points in this time series.

        Used for query result metadata and for validating that sufficient
        data exists before performing statistical aggregations.
        """
        return len(self.points)

    def to_dict(self) -> dict[str, Any]:
        """Convert the time series to a plain dictionary representation.

        This method serializes the entire time series including all data
        points, suitable for REST API responses or gRPC message conversion.
        """
        return {
            "metric_name": self.metric_name,
            "labels": dict(self.labels),
            "points": [p.to_dict() for p in self.points],
        }


@dataclass(frozen=True)
class Metric:
    """A named, typed metric with associated metadata and labels.

    Metric is the top-level entity that represents an observable quantity
    in the system. It carries the metric type (counter, gauge, or histogram)
    which determines how the metric should be aggregated and interpreted.
    The labels field provides dimensional data for filtering and grouping,
    while the service field identifies the originating service for
    multi-tenant analysis and service-level dashboards.
    """

    name: str
    metric_type: MetricType
    value: float
    timestamp: datetime
    service: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    unit: str = ""

    def to_data_point(self) -> DataPoint:
        """Convert this metric to a DataPoint for time series storage.

        This convenience method extracts the temporal and numeric aspects
        of the metric, discarding the metadata that is stored separately
        in the metric registry. Used by the ingestion pipeline when
        writing raw metrics to the time series database.
        """
        return DataPoint(timestamp=self.timestamp, value=self.value)

    def to_dict(self) -> dict[str, Any]:
        """Convert the metric to a plain dictionary representation.

        Includes all metadata fields for full-fidelity storage and
        retrieval. Adapters use this method when serializing metrics
        to ClickHouse or other storage backends.
        """
        return {
            "name": self.name,
            "metric_type": self.metric_type.value,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "service": self.service,
            "labels": dict(self.labels),
            "unit": self.unit,
        }
