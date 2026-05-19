"""
Report generation service for the Analytics service.

This module implements the report generation service that produces structured
analytical reports from time series data. Each report type encapsulates a
specific business analysis pattern with predefined metrics, dimensions, and
visualization recommendations. Reports can be generated in JSON, CSV, or PDF
format, and are cached for 5 minutes after generation to support repeated
downloads without regenerating the underlying data.

The service supports seven report types covering key business domains:
revenue summaries, order funnel analysis, inventory velocity tracking,
payment health monitoring, notification effectiveness, service SLA compliance,
and customer lifetime value estimation. Each report type has a dedicated
generation method that assembles the appropriate metric queries and formats
the results for the target audience.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models.aggregation import AggregationFunction, AggregationWindow
from ..models.report import Granularity, Report, ReportFormat, ReportType, TimeRange
from ..ports.outbound.event_store import EventRepository
from ..ports.outbound.time_series_store import TimeSeriesRepository

logger = logging.getLogger(__name__)


class ReportTypeNotFoundError(Exception):
    """Raised when a requested report type is not recognized."""
    pass


class InsufficientDataError(Exception):
    """Raised when there is not enough data to generate a report."""
    pass


class ReportGenerationTimeoutError(Exception):
    """Raised when report generation exceeds the time limit."""
    pass


class ReportService:
    """Report generation and formatting service.

    This service implements the GetReport inbound port by orchestrating
    metric queries, applying report-specific transformations, and formatting
    the output in the requested format. Reports are cached for 5 minutes
    after generation, and the service tracks generation metadata for audit
    and monitoring purposes.
    """

    # Mapping from granularity to aggregation window and function
    GRANULARITY_MAPPING: dict[Granularity, tuple[AggregationWindow, AggregationFunction]] = {
        Granularity.HOURLY: (AggregationWindow.ONE_HOUR, AggregationFunction.AVG),
        Granularity.DAILY: (AggregationWindow.ONE_DAY, AggregationFunction.AVG),
        Granularity.WEEKLY: (AggregationWindow.ONE_DAY, AggregationFunction.AVG),
        Granularity.MONTHLY: (AggregationWindow.ONE_DAY, AggregationFunction.AVG),
    }

    # Metric names associated with each report type
    REPORT_METRICS: dict[ReportType, list[str]] = {
        ReportType.REVENUE_SUMMARY: ["revenue.total", "payment.count", "refund.total"],
        ReportType.ORDER_FUNNEL: ["order.created", "order.completed", "order.cancelled"],
        ReportType.INVENTORY_VELOCITY: ["inventory.stock_level", "inventory.stockout_count"],
        ReportType.PAYMENT_HEALTH: ["payment.success_rate", "payment.error_rate", "payment.latency_p99"],
        ReportType.NOTIFICATION_EFFECTIVENESS: ["notification.sent", "notification.delivered", "notification.opened"],
        ReportType.SERVICE_SLA: ["service.availability", "service.latency_p99", "service.error_rate"],
        ReportType.CUSTOMER_LIFETIME_VALUE: ["customer.orders_total", "customer.revenue_total"],
    }

    def __init__(
        self,
        time_series_repo: TimeSeriesRepository,
        event_repo: EventRepository,
        cache_ttl_seconds: int = 300,
    ) -> None:
        """Initialize the report service with required dependencies.

        Args:
            time_series_repo: Repository for querying metric time series data.
            event_repo: Repository for event metadata and report configs.
            cache_ttl_seconds: Time-to-live for cached reports in seconds.
                Defaults to 300 seconds (5 minutes).
        """
        self._repo = time_series_repo
        self._event_repo = event_repo
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[datetime, Report]] = {}

    def get_report(
        self,
        report_type: ReportType,
        parameters: dict[str, str] | None = None,
        time_range: TimeRange | None = None,
        format: ReportFormat = ReportFormat.JSON,
        granularity: Granularity = Granularity.DAILY,
    ) -> Report:
        """Generate a pre-configured analytical report.

        Checks the cache for a recently generated report with matching
        parameters. If no cached report exists, queries the time series
        store for the metrics associated with the report type, applies
        report-specific transformations, and formats the output.

        Args:
            report_type: The type of report to generate.
            parameters: Optional parameters for dynamic customization.
            time_range: The temporal scope. Defaults to the last 7 days.
            format: The output format (JSON, CSV, PDF).
            granularity: The temporal resolution of report data points.

        Returns:
            A Report object containing the generated data and metadata.

        Raises:
            ReportTypeNotFoundError: If the report type is not recognized.
            InsufficientDataError: If no data is available for the report.
        """
        if time_range is None:
            time_range = TimeRange(
                start=datetime.now(timezone.utc) - timedelta(days=7),
                end=datetime.now(timezone.utc),
            )

        cache_key = self._build_cache_key(report_type, parameters, time_range, format, granularity)
        cached = self._get_cached_report(cache_key)
        if cached is not None:
            logger.info("Returning cached report: key=%s", cache_key)
            return cached

        metric_names = self.REPORT_METRICS.get(report_type)
        if metric_names is None:
            raise ReportTypeNotFoundError(f"Unknown report type: {report_type}")

        window, aggregation = self.GRANULARITY_MAPPING.get(
            granularity, (AggregationWindow.ONE_DAY, AggregationFunction.AVG)
        )

        series_data = self._repo.query(
            metric_names=metric_names,
            labels=parameters,
            time_range=time_range,
            window=window,
            aggregation=aggregation,
        )

        if not series_data or all(s.total_points == 0 for s in series_data):
            raise InsufficientDataError(
                f"No data available for report type {report_type.value} "
                f"in the specified time range."
            )

        report_data = self._transform_report_data(report_type, series_data, parameters)
        formatted_data = self._format_output(report_data, format)

        report = Report(
            report_id=str(uuid.uuid4()),
            report_type=report_type,
            time_range=time_range,
            format=format,
            generated_at=datetime.now(timezone.utc),
            data=formatted_data,
            parameters=parameters or {},
            granularity=granularity,
        )

        self._cache_report(cache_key, report)
        logger.info("Generated report: id=%s, type=%s, format=%s", report.report_id, report_type.value, format.value)

        return report

    def _transform_report_data(
        self,
        report_type: ReportType,
        series_data: list[Any],
        parameters: dict[str, str] | None,
    ) -> dict[str, Any]:
        """Apply report-type-specific transformations to the raw series data.

        Each report type has unique transformation logic that converts raw
        time series data into curated business insights. For example, the
        order funnel report computes conversion rates between stages, while
        the revenue summary report calculates daily and period totals.

        Args:
            report_type: The type of report being generated.
            series_data: The raw time series data from the query.
            parameters: Optional parameters for customization.

        Returns:
            A dictionary containing the transformed report data.
        """
        base_data = {
            "report_type": report_type.value,
            "metrics": {},
            "summary": {},
        }

        for series in series_data:
            base_data["metrics"][series.metric_name] = series.to_dict()
            values = [p.value for p in series.points]
            if values:
                base_data["summary"][series.metric_name] = {
                    "total": sum(values),
                    "average": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values),
                    "count": len(values),
                }

        if report_type == ReportType.ORDER_FUNNEL:
            base_data["analysis"] = self._compute_funnel_analysis(base_data["summary"])
        elif report_type == ReportType.REVENUE_SUMMARY:
            base_data["analysis"] = self._compute_revenue_analysis(base_data["summary"])

        return base_data

    def _compute_funnel_analysis(self, summary: dict[str, Any]) -> dict[str, Any]:
        """Compute order funnel conversion rates and drop-off analysis.

        The funnel analysis calculates the conversion rate from order
        creation to completion and identifies the drop-off at each stage.
        This is the most common business intelligence metric for e-commerce
        platforms.

        Args:
            summary: Summary statistics for each metric.

        Returns:
            A dictionary with conversion rates and drop-off analysis.
        """
        created = summary.get("order.created", {}).get("total", 0)
        completed = summary.get("order.completed", {}).get("total", 0)
        cancelled = summary.get("order.cancelled", {}).get("total", 0)

        conversion_rate = (completed / created * 100) if created > 0 else 0.0
        cancellation_rate = (cancelled / created * 100) if created > 0 else 0.0

        return {
            "conversion_rate": round(conversion_rate, 2),
            "cancellation_rate": round(cancellation_rate, 2),
            "drop_off_count": created - completed - cancelled,
        }

    def _compute_revenue_analysis(self, summary: dict[str, Any]) -> dict[str, Any]:
        """Compute revenue summary analysis with breakdowns.

        The revenue analysis calculates total revenue, refund rates,
        and net revenue. These are the primary financial metrics for
        executive reporting.

        Args:
            summary: Summary statistics for each metric.

        Returns:
            A dictionary with revenue analysis results.
        """
        total_revenue = summary.get("revenue.total", {}).get("total", 0)
        total_refunds = summary.get("refund.total", {}).get("total", 0)
        net_revenue = total_revenue - total_refunds
        refund_rate = (total_refunds / total_revenue * 100) if total_revenue > 0 else 0.0

        return {
            "total_revenue": round(total_revenue, 2),
            "total_refunds": round(total_refunds, 2),
            "net_revenue": round(net_revenue, 2),
            "refund_rate": round(refund_rate, 2),
        }

    def _format_output(self, data: dict[str, Any], format: ReportFormat) -> Any:
        """Format report data according to the requested output format.

        JSON format returns the data as-is for programmatic consumption.
        CSV format flattens the time series data into a tabular structure
        suitable for spreadsheet analysis. PDF format is indicated by a
        placeholder since actual PDF generation requires a template engine.

        Args:
            data: The report data dictionary.
            format: The desired output format.

        Returns:
            The formatted report data in the requested format.
        """
        if format == ReportFormat.JSON:
            return data
        elif format == ReportFormat.CSV:
            return self._format_csv(data)
        elif format == ReportFormat.PDF:
            return data
        else:
            return data

    def _format_csv(self, data: dict[str, Any]) -> str:
        """Convert report data to CSV format.

        Flattens the time series metrics into a tabular format with columns
        for metric name, timestamp, and value. This format is suitable for
        import into spreadsheet tools and data analysis platforms.

        Args:
            data: The report data dictionary.

        Returns:
            A CSV-formatted string.
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["metric_name", "timestamp", "value"])

        metrics = data.get("metrics", {})
        for metric_name, series in metrics.items():
            points = series.get("points", [])
            for point in points:
                writer.writerow([metric_name, point.get("timestamp", ""), point.get("value", "")])

        return output.getvalue()

    def _build_cache_key(
        self,
        report_type: ReportType,
        parameters: dict[str, str] | None,
        time_range: TimeRange,
        format: ReportFormat,
        granularity: Granularity,
    ) -> str:
        """Build a deterministic cache key for report deduplication.

        The cache key includes all parameters that affect the report output,
        ensuring that different parameter combinations produce different
        cache entries while identical requests reuse cached results.

        Args:
            report_type: The report type.
            parameters: Report parameters.
            time_range: The time range.
            format: The output format.
            granularity: The data granularity.

        Returns:
            A string cache key.
        """
        param_str = json.dumps(parameters or {}, sort_keys=True)
        return (
            f"{report_type.value}:{time_range.start.isoformat()}:"
            f"{time_range.end.isoformat()}:{format.value}:"
            f"{granularity.value}:{param_str}"
        )

    def _get_cached_report(self, cache_key: str) -> Report | None:
        """Retrieve a cached report if it exists and has not expired.

        Cached reports are stored with their generation timestamp. A report
        is considered expired if the time since generation exceeds the
        cache TTL. Expired entries are purged on access.

        Args:
            cache_key: The cache key to look up.

        Returns:
            The cached Report if valid, or None if not found or expired.
        """
        entry = self._cache.get(cache_key)
        if entry is None:
            return None

        cached_at, report = entry
        if (datetime.now(timezone.utc) - cached_at).total_seconds() > self._cache_ttl:
            del self._cache[cache_key]
            return None

        return report

    def _cache_report(self, cache_key: str, report: Report) -> None:
        """Store a generated report in the cache.

        Args:
            cache_key: The cache key for the report.
            report: The report to cache.
        """
        self._cache[cache_key] = (datetime.now(timezone.utc), report)
