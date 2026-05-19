"""
Contract test verifying the gRPC AnalyticsService proto interface
is satisfied by the handler.

Validates that the GrpcHandler implements all RPC methods defined
in analytics.v1.AnalyticsService proto specification:
  - GetReport
  - QueryMetrics (called GetMetrics in handler)
  - GetDashboard
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.adapters.inbound.grpc_handler import GrpcHandler
from src.domain.services.analytics_service import AnalyticsService
from src.domain.services.dashboard_service import DashboardService
from src.domain.services.report_service import ReportService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_analytics_service() -> MagicMock:
    return MagicMock(spec=AnalyticsService)


@pytest.fixture
def mock_dashboard_service() -> MagicMock:
    return MagicMock(spec=DashboardService)


@pytest.fixture
def mock_report_service() -> MagicMock:
    return MagicMock(spec=ReportService)


@pytest.fixture
def grpc_handler(
    mock_analytics_service: MagicMock,
    mock_dashboard_service: MagicMock,
    mock_report_service: MagicMock,
) -> GrpcHandler:
    return GrpcHandler(
        analytics_service=mock_analytics_service,
        dashboard_service=mock_dashboard_service,
        report_service=mock_report_service,
    )


# ---------------------------------------------------------------------------
# Proto interface satisfaction
# ---------------------------------------------------------------------------

class TestAnalyticsProtoContract:
    """Contract tests for the AnalyticsService gRPC interface.

    These tests verify that the GrpcHandler exposes all RPC methods
    defined in the analytics.v1.AnalyticsService proto specification.
    The proto defines three RPCs: GetReport, QueryMetrics, GetDashboard.
    """

    def test_handler_has_get_metrics_method(self, grpc_handler: GrpcHandler) -> None:
        """GetMetrics (QueryMetrics) RPC must be implemented."""
        assert hasattr(grpc_handler, "GetMetrics")
        assert callable(grpc_handler.GetMetrics)

    def test_handler_has_query_method(self, grpc_handler: GrpcHandler) -> None:
        """Query (traces) RPC must be implemented."""
        assert hasattr(grpc_handler, "Query")
        assert callable(grpc_handler.Query)

    def test_handler_has_get_dashboard_method(self, grpc_handler: GrpcHandler) -> None:
        """GetDashboard RPC must be implemented."""
        assert hasattr(grpc_handler, "GetDashboard")
        assert callable(grpc_handler.GetDashboard)

    def test_handler_has_get_report_method(self, grpc_handler: GrpcHandler) -> None:
        """GetReport RPC must be implemented."""
        assert hasattr(grpc_handler, "GetReport")
        assert callable(grpc_handler.GetReport)

    def test_all_rpc_methods_are_async(self, grpc_handler: GrpcHandler) -> None:
        """All RPC handler methods must be coroutines (async def)."""
        import asyncio
        for method_name in ("GetMetrics", "Query", "GetDashboard", "GetReport"):
            method = getattr(grpc_handler, method_name)
            assert asyncio.iscoroutinefunction(method), (
                f"{method_name} must be an async method"
            )

    def test_handler_accepts_analytics_service(self) -> None:
        """Handler must accept AnalyticsService dependency."""
        handler = GrpcHandler(
            analytics_service=MagicMock(spec=AnalyticsService),
            dashboard_service=MagicMock(spec=DashboardService),
            report_service=MagicMock(spec=ReportService),
        )
        assert handler._analytics_service is not None

    def test_handler_accepts_report_service(self) -> None:
        """Handler must accept ReportService dependency for GetReport."""
        handler = GrpcHandler(
            analytics_service=MagicMock(spec=AnalyticsService),
            dashboard_service=MagicMock(spec=DashboardService),
            report_service=MagicMock(spec=ReportService),
        )
        assert handler._report_service is not None

    def test_handler_accepts_dashboard_service(self) -> None:
        """Handler must accept DashboardService dependency for GetDashboard."""
        handler = GrpcHandler(
            analytics_service=MagicMock(spec=AnalyticsService),
            dashboard_service=MagicMock(spec=DashboardService),
            report_service=MagicMock(spec=ReportService),
        )
        assert handler._dashboard_service is not None


# ---------------------------------------------------------------------------
# Request/Response contract
# ---------------------------------------------------------------------------

class TestAnalyticsRequestResponseContract:
    """Tests verifying request/response mapping aligns with proto messages."""

    def test_parse_time_range_returns_none_for_empty(self, grpc_handler: GrpcHandler) -> None:
        result = grpc_handler._parse_time_range(None, None)
        assert result is None

    def test_parse_step_maps_enum_values(self, grpc_handler: GrpcHandler) -> None:
        from src.domain.models.aggregation import AggregationWindow
        assert grpc_handler._parse_step(0) == AggregationWindow.ONE_MINUTE
        assert grpc_handler._parse_step(1) == AggregationWindow.ONE_HOUR
        assert grpc_handler._parse_step(2) == AggregationWindow.ONE_DAY

    def test_parse_aggregation_maps_enum_values(self, grpc_handler: GrpcHandler) -> None:
        from src.domain.models.aggregation import AggregationFunction
        assert grpc_handler._parse_aggregation(0) == AggregationFunction.AVG
        assert grpc_handler._parse_aggregation(1) == AggregationFunction.SUM
        assert grpc_handler._parse_aggregation(6) == AggregationFunction.P99
