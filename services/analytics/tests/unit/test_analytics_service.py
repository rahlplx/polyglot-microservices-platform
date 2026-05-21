"""
Unit tests for AnalyticsService.

Tests the core analytics query orchestration service with mocked outbound
ports. Validates get_metrics, query_traces, get_dependencies, time range
validation, and optimal window selection logic.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from src.domain.models.aggregation import AggregationFunction, AggregationWindow
from src.domain.models.metric import DataPoint, TimeSeries
from src.domain.models.report import TimeRange
from src.domain.services.analytics_service import (
    AnalyticsService,
    InvalidTimeRangeError,
    QueryTooBroadError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_time_series_repo() -> MagicMock:
    repo = MagicMock()
    repo.query.return_value = [
        TimeSeries(
            metric_name="test.metric",
            labels={"service": "catalog"},
            points=[
                DataPoint(timestamp=datetime.now(timezone.utc), value=1.0),
                DataPoint(timestamp=datetime.now(timezone.utc) + timedelta(minutes=1), value=2.0),
            ],
        )
    ]
    return repo


@pytest.fixture
def mock_event_repo() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_otel_processor() -> MagicMock:
    processor = MagicMock()
    processor.get_trace.return_value = {
        "trace_id": "abc123",
        "spans": [],
    }
    processor.query_traces.return_value = [
        {"trace_id": "t1", "service_name": "catalog"},
    ]
    processor.get_dependencies.return_value = {
        "nodes": [{"id": "catalog"}, {"id": "order"}],
        "edges": [{"source": "catalog", "target": "order", "latency_p99": 50}],
    }
    return processor


@pytest.fixture
def analytics_service(
    mock_time_series_repo: MagicMock,
    mock_event_repo: MagicMock,
    mock_otel_processor: MagicMock,
) -> AnalyticsService:
    return AnalyticsService(
        time_series_repo=mock_time_series_repo,
        event_repo=mock_event_repo,
        otel_processor=mock_otel_processor,
        max_query_range_days=90,
    )


@pytest.fixture
def one_hour_range() -> TimeRange:
    now = datetime.now(timezone.utc)
    return TimeRange(start=now - timedelta(hours=1), end=now)


@pytest.fixture
def wide_range() -> TimeRange:
    now = datetime.now(timezone.utc)
    return TimeRange(start=now - timedelta(days=100), end=now)


# ---------------------------------------------------------------------------
# get_metrics
# ---------------------------------------------------------------------------

class TestGetMetrics:
    """Tests for AnalyticsService.get_metrics()."""

    def test_returns_empty_for_empty_metric_names(
        self, analytics_service: AnalyticsService
    ) -> None:
        result = analytics_service.get_metrics(metric_names=[])
        assert result == []

    def test_delegates_to_time_series_repo(
        self,
        analytics_service: AnalyticsService,
        mock_time_series_repo: MagicMock,
        one_hour_range: TimeRange,
    ) -> None:
        result = analytics_service.get_metrics(
            metric_names=["order.count"],
            time_range=one_hour_range,
        )
        mock_time_series_repo.query.assert_called_once()
        assert len(result) == 1
        assert result[0].metric_name == "test.metric"

    def test_default_time_range_when_none(
        self,
        analytics_service: AnalyticsService,
        mock_time_series_repo: MagicMock,
    ) -> None:
        analytics_service.get_metrics(metric_names=["order.count"])
        call_args = mock_time_series_repo.query.call_args
        time_range = call_args.kwargs.get("time_range") or call_args[1].get("time_range")
        assert time_range is not None
        duration = time_range.duration_seconds
        assert 3590 < duration < 3610  # ~1 hour

    def test_raises_on_exceeds_max_range(
        self, analytics_service: AnalyticsService, wide_range: TimeRange
    ) -> None:
        with pytest.raises(InvalidTimeRangeError, match="exceeds the maximum"):
            analytics_service.get_metrics(
                metric_names=["order.count"],
                time_range=wide_range,
            )

    def test_passes_labels_to_repo(
        self,
        analytics_service: AnalyticsService,
        mock_time_series_repo: MagicMock,
        one_hour_range: TimeRange,
    ) -> None:
        labels = {"service": "payment"}
        analytics_service.get_metrics(
            metric_names=["payment.latency"],
            labels=labels,
            time_range=one_hour_range,
        )
        call_kwargs = mock_time_series_repo.query.call_args
        kw = call_kwargs.kwargs if call_kwargs.kwargs else call_args[1]
        assert kw.get("labels") == labels


# ---------------------------------------------------------------------------
# query_traces
# ---------------------------------------------------------------------------

class TestQueryTraces:
    """Tests for AnalyticsService.query_traces()."""

    def test_direct_trace_lookup(
        self,
        analytics_service: AnalyticsService,
        mock_otel_processor: MagicMock,
    ) -> None:
        result = analytics_service.query_traces(trace_id="abc123")
        mock_otel_processor.get_trace.assert_called_once_with("abc123")
        assert len(result) == 1
        assert result[0]["trace_id"] == "abc123"

    def test_returns_empty_for_missing_trace(
        self,
        analytics_service: AnalyticsService,
        mock_otel_processor: MagicMock,
    ) -> None:
        mock_otel_processor.get_trace.return_value = None
        result = analytics_service.query_traces(trace_id="nonexistent")
        assert result == []

    def test_raises_when_query_too_broad(
        self, analytics_service: AnalyticsService
    ) -> None:
        with pytest.raises(QueryTooBroadError, match="at least one of"):
            analytics_service.query_traces()

    def test_delegates_filtered_search(
        self,
        analytics_service: AnalyticsService,
        mock_otel_processor: MagicMock,
    ) -> None:
        result = analytics_service.query_traces(service_name="catalog")
        mock_otel_processor.query_traces.assert_called_once()
        assert len(result) == 1

    def test_limits_max_results(
        self,
        analytics_service: AnalyticsService,
        mock_otel_processor: MagicMock,
    ) -> None:
        analytics_service.query_traces(service_name="catalog", limit=200)
        call_kwargs = mock_otel_processor.query_traces.call_args
        kw = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert kw.get("limit") == 100

    def test_passes_duration_filters(
        self,
        analytics_service: AnalyticsService,
        mock_otel_processor: MagicMock,
    ) -> None:
        analytics_service.query_traces(
            service_name="catalog",
            min_duration_ms=10,
            max_duration_ms=5000,
        )
        call_kwargs = mock_otel_processor.query_traces.call_args
        kw = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert kw.get("min_duration_ms") == 10
        assert kw.get("max_duration_ms") == 5000


# ---------------------------------------------------------------------------
# get_dependencies
# ---------------------------------------------------------------------------

class TestGetDependencies:
    """Tests for AnalyticsService.get_dependencies()."""

    def test_returns_dependency_graph(
        self,
        analytics_service: AnalyticsService,
        mock_otel_processor: MagicMock,
    ) -> None:
        result = analytics_service.get_dependencies()
        mock_otel_processor.get_dependencies.assert_called_once()
        assert "nodes" in result
        assert "edges" in result

    def test_default_time_range_when_none(
        self,
        analytics_service: AnalyticsService,
        mock_otel_processor: MagicMock,
    ) -> None:
        analytics_service.get_dependencies()
        call_kwargs = mock_otel_processor.get_dependencies.call_args
        kw = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert kw.get("start_time") is not None
        assert kw.get("end_time") is not None

    def test_uses_provided_time_range(
        self,
        analytics_service: AnalyticsService,
        mock_otel_processor: MagicMock,
        one_hour_range: TimeRange,
    ) -> None:
        analytics_service.get_dependencies(time_range=one_hour_range)
        call_kwargs = mock_otel_processor.get_dependencies.call_args
        kw = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert kw.get("start_time") == one_hour_range.start
        assert kw.get("end_time") == one_hour_range.end


# ---------------------------------------------------------------------------
# Time range validation
# ---------------------------------------------------------------------------

class TestTimeRangeValidation:
    """Tests for AnalyticsService._validate_time_range()."""

    def test_accepts_valid_range(self, analytics_service: AnalyticsService) -> None:
        now = datetime.now(timezone.utc)
        time_range = TimeRange(start=now - timedelta(hours=1), end=now)
        # Should not raise
        analytics_service._validate_time_range(time_range)

    def test_rejects_range_exceeding_max(self, analytics_service: AnalyticsService) -> None:
        now = datetime.now(timezone.utc)
        time_range = TimeRange(start=now - timedelta(days=91), end=now)
        with pytest.raises(InvalidTimeRangeError):
            analytics_service._validate_time_range(time_range)

    def test_custom_max_range(self) -> None:
        service = AnalyticsService(
            time_series_repo=MagicMock(),
            event_repo=MagicMock(),
            otel_processor=MagicMock(),
            max_query_range_days=30,
        )
        now = datetime.now(timezone.utc)
        time_range = TimeRange(start=now - timedelta(days=31), end=now)
        with pytest.raises(InvalidTimeRangeError):
            service._validate_time_range(time_range)


# ---------------------------------------------------------------------------
# Optimal window selection
# ---------------------------------------------------------------------------

class TestOptimalWindowSelection:
    """Tests for AnalyticsService._select_optimal_window()."""

    def test_returns_requested_window_for_short_range(
        self, analytics_service: AnalyticsService
    ) -> None:
        now = datetime.now(timezone.utc)
        time_range = TimeRange(start=now - timedelta(hours=1), end=now)
        result = analytics_service._select_optimal_window(
            time_range, AggregationWindow.ONE_MINUTE
        )
        assert result == AggregationWindow.ONE_MINUTE

    def test_upgrades_one_minute_to_five_minutes_beyond_72h(
        self, analytics_service: AnalyticsService
    ) -> None:
        now = datetime.now(timezone.utc)
        time_range = TimeRange(start=now - timedelta(hours=73), end=now)
        result = analytics_service._select_optimal_window(
            time_range, AggregationWindow.ONE_MINUTE
        )
        assert result == AggregationWindow.FIVE_MINUTES

    def test_upgrades_five_minutes_to_one_hour_beyond_720h(
        self, analytics_service: AnalyticsService
    ) -> None:
        now = datetime.now(timezone.utc)
        time_range = TimeRange(start=now - timedelta(hours=721), end=now)
        result = analytics_service._select_optimal_window(
            time_range, AggregationWindow.FIVE_MINUTES
        )
        assert result == AggregationWindow.ONE_HOUR

    def test_upgrades_one_hour_to_one_day_beyond_4320h(
        self, analytics_service: AnalyticsService
    ) -> None:
        now = datetime.now(timezone.utc)
        time_range = TimeRange(start=now - timedelta(hours=4321), end=now)
        result = analytics_service._select_optimal_window(
            time_range, AggregationWindow.ONE_HOUR
        )
        assert result == AggregationWindow.ONE_DAY

    def test_no_upgrade_for_one_day_window(
        self, analytics_service: AnalyticsService
    ) -> None:
        now = datetime.now(timezone.utc)
        time_range = TimeRange(start=now - timedelta(hours=5000), end=now)
        result = analytics_service._select_optimal_window(
            time_range, AggregationWindow.ONE_DAY
        )
        assert result == AggregationWindow.ONE_DAY
