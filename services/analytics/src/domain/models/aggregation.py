"""
Aggregation domain model for the Analytics service.

This module defines the aggregation-related value objects used by the
aggregation engine to compute time-windowed rollups of metric data.
The AggregationWindow specifies the time interval for grouping data points,
while the AggregationFunction determines the mathematical operation applied
to each group. The AggregatedDataPoint represents the result of applying
an aggregation function to a set of raw data points within a window.

Pre-computed rollups are the foundation of dashboard performance: rather
than scanning billions of raw data points for every dashboard refresh,
the system queries pre-aggregated tables that contain sums, averages,
and percentiles at fixed intervals (1 minute, 5 minutes, 1 hour, 1 day).
This design trades storage cost for query speed, which is the standard
trade-off in time-series databases like ClickHouse.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class AggregationWindow(Enum):
    """Predefined time intervals for rollup aggregation.

    Each window size corresponds to a pre-computed rollup table in ClickHouse.
    The 1-minute window provides near-real-time granularity for operational
    dashboards. The 5-minute window balances detail and storage efficiency
    for medium-term analysis. The 1-hour and 1-day windows support long-term
    trend analysis and reporting with dramatically reduced storage requirements.
    """

    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    ONE_HOUR = "1h"
    ONE_DAY = "1d"

    @property
    def timedelta(self) -> timedelta:
        """Return the Python timedelta corresponding to this window size.

        This property enables the aggregation engine to compute window
        boundaries without magic numbers, ensuring consistency between
        the window definition and the actual time intervals used in
        aggregation calculations.
        """
        mapping: dict[AggregationWindow, timedelta] = {
            AggregationWindow.ONE_MINUTE: timedelta(minutes=1),
            AggregationWindow.FIVE_MINUTES: timedelta(minutes=5),
            AggregationWindow.ONE_HOUR: timedelta(hours=1),
            AggregationWindow.ONE_DAY: timedelta(days=1),
        }
        return mapping[self]


class AggregationFunction(Enum):
    """Mathematical operations for combining data points within a window.

    The standard statistical functions (sum, avg, min, max, count) support
    general-purpose aggregation. The percentile functions (p50, p95, p99)
    are critical for latency analysis: P50 represents the median experience,
    P95 captures the long tail, and P99 identifies extreme outliers that
    may indicate systemic issues.
    """

    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    P50 = "p50"
    P95 = "p95"
    P99 = "p99"


@dataclass(frozen=True)
class AggregatedDataPoint:
    """The result of applying an aggregation function to a time window.

    An AggregatedDataPoint captures the output of the aggregation engine:
    a single numeric value representing the result of combining all raw
    data points within a specific time window using a specific aggregation
    function. The sample_count field records how many raw data points
    contributed to this aggregation, which is essential for statistical
    significance analysis and for detecting sparse data regions where
    percentiles may be unreliable.
    """

    timestamp: datetime
    value: float
    aggregation_function: AggregationFunction
    window: AggregationWindow
    sample_count: int = 0

    @property
    def is_significant(self) -> bool:
        """Determine if this data point has sufficient samples for reliability.

        A minimum sample threshold of 5 is used as a heuristic: fewer than
        5 samples may produce unreliable percentile estimates and should be
        flagged in dashboards and reports. This threshold can be adjusted
        per metric type if needed.
        """
        return self.sample_count >= 5

    def to_dict(self) -> dict[str, Any]:
        """Convert the aggregated data point to a plain dictionary.

        Includes the sample count for downstream consumers that need to
        assess data quality and statistical significance.
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "value": self.value,
            "aggregation_function": self.aggregation_function.value,
            "window": self.window.value,
            "sample_count": self.sample_count,
        }
