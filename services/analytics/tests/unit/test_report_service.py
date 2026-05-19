"""
Unit tests for ReportService.

Tests the report generation service with mocked repositories. Validates
get_report with caching, report type not found, insufficient data,
and CSV formatting logic.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from src.domain.models.aggregation import AggregationFunction, AggregationWindow
from src.domain.models.metric import DataPoint, TimeSeries
from src.domain.models.report import (
    Granularity,
    Report,
    ReportFormat,
    ReportType,
    TimeRange,
)
from src.domain.services.report_service import (
    InsufficientDataError,
    ReportService,
    ReportTypeNotFoundError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_series(metric_name: str, num_points: int = 3) -> TimeSeries:
    """Create a TimeSeries with sample data points."""
    now = datetime.now(timezone.utc)
    return TimeSeries(
        metric_name=metric_name,
        labels={},
        points=[
            DataPoint(timestamp=now - timedelta(minutes=i), value=float(i + 1))
            for i in range(num_points)
        ],
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    # Default: return series with data
    repo.query.return_value = [
        _make_series("revenue.total"),
        _make_series("payment.count"),
        _make_series("refund.total"),
    ]
    return repo


@pytest.fixture
def mock_event_repo() -> MagicMock:
    return MagicMock()


@pytest.fixture
def report_service(mock_repo: MagicMock, mock_event_repo: MagicMock) -> ReportService:
    return ReportService(
        time_series_repo=mock_repo,
        event_repo=mock_event_repo,
        cache_ttl_seconds=300,
    )


@pytest.fixture
def seven_day_range() -> TimeRange:
    now = datetime.now(timezone.utc)
    return TimeRange(start=now - timedelta(days=7), end=now)


# ---------------------------------------------------------------------------
# get_report — happy path
# ---------------------------------------------------------------------------

class TestGetReport:
    """Tests for ReportService.get_report()."""

    def test_returns_report_with_data(
        self,
        report_service: ReportService,
        seven_day_range: TimeRange,
    ) -> None:
        report = report_service.get_report(
            report_type=ReportType.REVENUE_SUMMARY,
            time_range=seven_day_range,
        )
        assert isinstance(report, Report)
        assert report.report_type == ReportType.REVENUE_SUMMARY
        assert report.format == ReportFormat.JSON
        assert report.data is not None

    def test_report_has_generated_at_timestamp(
        self,
        report_service: ReportService,
        seven_day_range: TimeRange,
    ) -> None:
        report = report_service.get_report(
            report_type=ReportType.REVENUE_SUMMARY,
            time_range=seven_day_range,
        )
        assert report.generated_at is not None

    def test_default_time_range_is_seven_days(
        self,
        report_service: ReportService,
        mock_repo: MagicMock,
    ) -> None:
        report_service.get_report(report_type=ReportType.REVENUE_SUMMARY)
        call_kwargs = mock_repo.query.call_args
        kw = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        time_range = kw.get("time_range")
        assert time_range is not None
        assert 6 * 86400 < time_range.duration_seconds < 8 * 86400

    def test_queries_correct_metrics_for_report_type(
        self,
        report_service: ReportService,
        mock_repo: MagicMock,
        seven_day_range: TimeRange,
    ) -> None:
        report_service.get_report(
            report_type=ReportType.ORDER_FUNNEL,
            time_range=seven_day_range,
        )
        call_kwargs = mock_repo.query.call_args
        kw = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        metric_names = kw.get("metric_names", [])
        assert "order.created" in metric_names
        assert "order.completed" in metric_names
        assert "order.cancelled" in metric_names


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

class TestReportCaching:
    """Tests for report caching behavior."""

    def test_returns_cached_report_on_second_call(
        self,
        report_service: ReportService,
        mock_repo: MagicMock,
        seven_day_range: TimeRange,
    ) -> None:
        report1 = report_service.get_report(
            report_type=ReportType.REVENUE_SUMMARY,
            time_range=seven_day_range,
        )
        report2 = report_service.get_report(
            report_type=ReportType.REVENUE_SUMMARY,
            time_range=seven_day_range,
        )
        # Second call should not query the repo again
        assert mock_repo.query.call_count == 1
        assert report1.report_id == report2.report_id

    def test_cache_miss_after_ttl_expiry(
        self,
        report_service: ReportService,
        mock_repo: MagicMock,
        seven_day_range: TimeRange,
    ) -> None:
        report_service._cache_ttl = 0  # Expire immediately
        report_service.get_report(
            report_type=ReportType.REVENUE_SUMMARY,
            time_range=seven_day_range,
        )
        report_service.get_report(
            report_type=ReportType.REVENUE_SUMMARY,
            time_range=seven_day_range,
        )
        # Both calls should hit the repo
        assert mock_repo.query.call_count == 2

    def test_different_params_produce_different_cache_keys(
        self,
        report_service: ReportService,
        mock_repo: MagicMock,
        seven_day_range: TimeRange,
    ) -> None:
        report_service.get_report(
            report_type=ReportType.REVENUE_SUMMARY,
            time_range=seven_day_range,
            format=ReportFormat.JSON,
        )
        report_service.get_report(
            report_type=ReportType.REVENUE_SUMMARY,
            time_range=seven_day_range,
            format=ReportFormat.CSV,
        )
        assert mock_repo.query.call_count == 2


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestReportErrors:
    """Tests for error handling in report generation."""

    def test_raises_on_unknown_report_type(
        self,
        report_service: ReportService,
        seven_day_range: TimeRange,
    ) -> None:
        # Create a mock report type that is not in REPORT_METRICS
        with pytest.raises(ReportTypeNotFoundError, match="Unknown report type"):
            report_service.get_report(
                report_type=MagicMock(value="nonexistent_report"),
                time_range=seven_day_range,
            )

    def test_raises_on_insufficient_data(
        self,
        report_service: ReportService,
        mock_repo: MagicMock,
        seven_day_range: TimeRange,
    ) -> None:
        # Return series with zero points
        mock_repo.query.return_value = [
            TimeSeries(metric_name="test", points=[]),
        ]
        with pytest.raises(InsufficientDataError, match="No data available"):
            report_service.get_report(
                report_type=ReportType.REVENUE_SUMMARY,
                time_range=seven_day_range,
            )

    def test_raises_on_empty_query_result(
        self,
        report_service: ReportService,
        mock_repo: MagicMock,
        seven_day_range: TimeRange,
    ) -> None:
        mock_repo.query.return_value = []
        with pytest.raises(InsufficientDataError):
            report_service.get_report(
                report_type=ReportType.REVENUE_SUMMARY,
                time_range=seven_day_range,
            )


# ---------------------------------------------------------------------------
# CSV formatting
# ---------------------------------------------------------------------------

class TestCSVFormatting:
    """Tests for CSV output formatting."""

    def test_csv_output_contains_header(
        self,
        report_service: ReportService,
        seven_day_range: TimeRange,
    ) -> None:
        report = report_service.get_report(
            report_type=ReportType.REVENUE_SUMMARY,
            time_range=seven_day_range,
            format=ReportFormat.CSV,
        )
        csv_data = report.data
        assert "metric_name" in csv_data
        assert "timestamp" in csv_data
        assert "value" in csv_data

    def test_csv_output_contains_metric_data(
        self,
        report_service: ReportService,
        seven_day_range: TimeRange,
    ) -> None:
        report = report_service.get_report(
            report_type=ReportType.REVENUE_SUMMARY,
            time_range=seven_day_range,
            format=ReportFormat.CSV,
        )
        csv_data = report.data
        assert "revenue.total" in csv_data

    def test_json_format_returns_dict(
        self,
        report_service: ReportService,
        seven_day_range: TimeRange,
    ) -> None:
        report = report_service.get_report(
            report_type=ReportType.REVENUE_SUMMARY,
            time_range=seven_day_range,
            format=ReportFormat.JSON,
        )
        assert isinstance(report.data, dict)
