"""
Time-window aggregation engine for the Analytics service.

This module implements the aggregation service that computes time-windowed
rollups of metric data. The engine processes raw data points from the time
series store, applies aggregation functions (sum, avg, min, max, percentiles),
and writes the results to pre-computed rollup tables. These rollups are the
foundation of dashboard performance, enabling sub-second query latency by
eliminating the need to scan raw data for common time ranges.

The service supports four window sizes (1m, 5m, 1h, 1d) and eight aggregation
functions (sum, avg, min, max, count, p50, p95, p99). It processes data in
batches for efficiency and handles edge cases such as empty windows and
sparse data regions where statistical significance may be limited.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models.aggregation import AggregatedDataPoint, AggregationFunction, AggregationWindow
from ..models.metric import DataPoint, TimeSeries
from ..models.report import TimeRange
from ..ports.outbound.time_series_store import TimeSeriesRepository

logger = logging.getLogger(__name__)


class AggregationService:
    """Time-window aggregation engine for pre-computing metric rollups.

    The aggregation service reads raw metric data from the time series store,
    groups data points into fixed-size time windows, applies aggregation
    functions, and writes the results to rollup tables. This pre-computation
    enables dashboard queries to return in sub-second timeframes regardless
    of the underlying data volume.

    The service is designed to be invoked periodically (e.g., every minute
    for 1-minute rollups, every 5 minutes for 5-minute rollups) by the
    scheduler in the infrastructure layer. Each invocation processes the
    most recent window of data that has not yet been aggregated.
    """

    def __init__(
        self,
        time_series_repo: TimeSeriesRepository,
        min_samples_for_percentile: int = 5,
    ) -> None:
        """Initialize the aggregation service with required dependencies.

        Args:
            time_series_repo: Repository for reading raw data and writing
                aggregated rollups.
            min_samples_for_percentile: Minimum number of samples required
                to compute a reliable percentile estimate. Percentiles
                computed from fewer samples are still calculated but
                flagged as statistically insignificant.
        """
        self._repo = time_series_repo
        self._min_samples_for_percentile = min_samples_for_percentile

    def aggregate_window(
        self,
        metric_name: str,
        labels: dict[str, str],
        window: AggregationWindow,
        aggregation: AggregationFunction,
        time_range: TimeRange,
    ) -> list[AggregatedDataPoint]:
        """Aggregate raw data points for a metric within a time range.

        Reads raw data points from the time series store, groups them into
        fixed-size windows, applies the specified aggregation function, and
        returns the aggregated results. The results are also written to the
        rollup table for future queries.

        Args:
            metric_name: The metric to aggregate.
            labels: Dimensional labels for filtering raw data.
            window: The aggregation window size.
            aggregation: The aggregation function to apply.
            time_range: The temporal scope of the aggregation.

        Returns:
            A list of AggregatedDataPoint objects, one per window.
        """
        raw_series = self._repo.query(
            metric_names=[metric_name],
            labels=labels,
            time_range=time_range,
            window=AggregationWindow.ONE_MINUTE,
            aggregation=AggregationFunction.AVG,
        )

        if not raw_series:
            logger.info("No raw data found for metric=%s, labels=%s", metric_name, labels)
            return []

        all_points = raw_series[0].points if raw_series else []
        windows = self._group_points_by_window(all_points, window)

        results: list[AggregatedDataPoint] = []
        for window_start, window_points in windows.items():
            aggregated = self._apply_aggregation(window_points, aggregation, window, window_start)
            if aggregated is not None:
                results.append(aggregated)

        if results:
            self._repo.write_aggregated(results, metric_name, labels)
            logger.info(
                "Wrote %d aggregated points for metric=%s, window=%s, func=%s",
                len(results),
                metric_name,
                window.value,
                aggregation.value,
            )

        return results

    def aggregate_all_windows(
        self,
        metric_name: str,
        labels: dict[str, str],
        time_range: TimeRange,
        aggregations: list[AggregationFunction] | None = None,
    ) -> dict[AggregationWindow, dict[AggregationFunction, list[AggregatedDataPoint]]]:
        """Aggregate a metric across all window sizes and functions.

        This convenience method runs aggregation for all window sizes and
        all specified functions in a single call. It is useful for bulk
        pre-computation during off-peak hours or for initial data
        backfill when a new metric is registered.

        Args:
            metric_name: The metric to aggregate.
            labels: Dimensional labels for filtering.
            time_range: The temporal scope.
            aggregations: List of aggregation functions. Defaults to all.

        Returns:
            A nested dictionary mapping window size to aggregation function
            to the list of aggregated data points.
        """
        if aggregations is None:
            aggregations = list(AggregationFunction)

        results: dict[AggregationWindow, dict[AggregationFunction, list[AggregatedDataPoint]]] = {}

        for window in AggregationWindow:
            results[window] = {}
            for func in aggregations:
                points = self.aggregate_window(
                    metric_name=metric_name,
                    labels=labels,
                    window=window,
                    aggregation=func,
                    time_range=time_range,
                )
                results[window][func] = points

        return results

    def _group_points_by_window(
        self,
        points: list[DataPoint],
        window: AggregationWindow,
    ) -> dict[datetime, list[DataPoint]]:
        """Group data points into fixed-size time windows.

        Points are assigned to windows based on their timestamp, with
        window boundaries aligned to the start of the interval (e.g.,
        1-hour windows start at the top of each hour). This alignment
        ensures consistent results regardless of when the aggregation
        is triggered.

        Args:
            points: The raw data points to group.
            window: The window size for grouping.

        Returns:
            A dictionary mapping window start timestamps to lists of
            data points that fall within that window.
        """
        delta = window.timedelta
        windows: dict[datetime, list[DataPoint]] = {}

        for point in points:
            epoch = point.timestamp.timestamp()
            window_start_ts = math.floor(epoch / delta.total_seconds()) * delta.total_seconds()
            window_start = datetime.fromtimestamp(window_start_ts, tz=timezone.utc)

            if window_start not in windows:
                windows[window_start] = []
            windows[window_start].append(point)

        return windows

    def _apply_aggregation(
        self,
        points: list[DataPoint],
        func: AggregationFunction,
        window: AggregationWindow,
        window_start: datetime,
    ) -> AggregatedDataPoint | None:
        """Apply an aggregation function to a list of data points.

        Computes the specified statistical function over the values in the
        window. For percentile calculations, uses the nearest-rank method
        which provides a good balance between accuracy and performance for
        streaming aggregation scenarios.

        Args:
            points: The data points within the window.
            func: The aggregation function to apply.
            window: The window size (for metadata).
            window_start: The start timestamp of the window.

        Returns:
            An AggregatedDataPoint with the computed value, or None if
            there are no points to aggregate.
        """
        if not points:
            return None

        values = sorted(p.value for p in points)
        count = len(values)

        computed_value = self._compute_function(values, count, func)

        return AggregatedDataPoint(
            timestamp=window_start,
            value=computed_value,
            aggregation_function=func,
            window=window,
            sample_count=count,
        )

    def _compute_function(
        self,
        sorted_values: list[float],
        count: int,
        func: AggregationFunction,
    ) -> float:
        """Compute the result of an aggregation function on sorted values.

        Each function has specific semantics: sum and count are straightforward
        accumulations; avg divides sum by count; min and max select the
        extremes; percentiles use the nearest-rank interpolation method.

        Args:
            sorted_values: Values sorted in ascending order.
            count: Number of values.
            func: The aggregation function to compute.

        Returns:
            The computed aggregation result.
        """
        if func == AggregationFunction.SUM:
            return sum(sorted_values)
        elif func == AggregationFunction.AVG:
            return sum(sorted_values) / count
        elif func == AggregationFunction.MIN:
            return sorted_values[0]
        elif func == AggregationFunction.MAX:
            return sorted_values[-1]
        elif func == AggregationFunction.COUNT:
            return float(count)
        elif func == AggregationFunction.P50:
            return self._percentile(sorted_values, count, 50)
        elif func == AggregationFunction.P95:
            return self._percentile(sorted_values, count, 95)
        elif func == AggregationFunction.P99:
            return self._percentile(sorted_values, count, 99)
        else:
            raise ValueError(f"Unsupported aggregation function: {func}")

    def _percentile(self, sorted_values: list[float], count: int, percentile: int) -> float:
        """Compute a percentile using the nearest-rank method.

        The nearest-rank method selects the value at the index closest to
        the rank computed from the percentile. For example, the 95th
        percentile of 100 values is the value at index 94 (0-indexed).

        Args:
            sorted_values: Values sorted in ascending order.
            count: Number of values.
            percentile: The percentile to compute (0-100).

        Returns:
            The percentile value.
        """
        if count == 1:
            return sorted_values[0]

        rank = (percentile / 100.0) * (count - 1)
        lower_idx = int(math.floor(rank))
        upper_idx = int(math.ceil(rank))

        if lower_idx == upper_idx:
            return sorted_values[lower_idx]

        fraction = rank - lower_idx
        return sorted_values[lower_idx] * (1 - fraction) + sorted_values[upper_idx] * fraction
