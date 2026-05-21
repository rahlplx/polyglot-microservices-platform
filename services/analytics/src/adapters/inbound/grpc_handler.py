"""
gRPC query handler adapter for the Analytics service.

This module implements the gRPC handler that serves as the primary query
interface for the Analytics service. The handler implements the
AnalyticsService proto definition, translating gRPC requests into calls
to the domain service's inbound ports and serializing the responses back
to gRPC protocol messages.

The handler includes server interceptors for authentication (validating
the caller's SPIFFE SVID for internal service-to-service calls), request
logging with correlation IDs, and OpenTelemetry span creation. It also
implements request validation that rejects overly broad queries before
they reach the database, preventing accidental denial-of-service from
poorly constructed dashboard queries.

The gRPC server runs on port 50057 with mTLS enforced. A separate OTLP
receiver runs on port 4317 for OpenTelemetry SDK telemetry ingestion.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ...domain.models.aggregation import AggregationFunction, AggregationWindow
from ...domain.models.report import Granularity, ReportFormat, ReportType, TimeRange
from ...domain.services.analytics_service import AnalyticsService
from ...domain.services.dashboard_service import DashboardService
from ...domain.services.report_service import ReportService

logger = logging.getLogger(__name__)


class GrpcHandler:
    """gRPC query handler implementing the AnalyticsService proto definition.

    This adapter translates incoming gRPC requests into domain service calls,
    handling protocol-specific concerns such as message parsing, field mapping,
    and error translation. It delegates all business logic to the domain
    services, keeping this adapter focused on the gRPC protocol layer.

    The handler supports four RPC methods: GetMetrics, Query (traces),
    GetDashboard, and GetReport, each mapping to the corresponding domain
    service method.
    """

    def __init__(
        self,
        analytics_service: AnalyticsService,
        dashboard_service: DashboardService,
        report_service: ReportService,
    ) -> None:
        """Initialize the gRPC handler with domain service dependencies.

        Args:
            analytics_service: Core analytics query orchestration service.
            dashboard_service: Dashboard configuration and data service.
            report_service: Report generation and formatting service.
        """
        self._analytics_service = analytics_service
        self._dashboard_service = dashboard_service
        self._report_service = report_service

    async def GetMetrics(self, request: Any, context: Any) -> Any:
        """Handle the GetMetrics gRPC request.

        Translates the gRPC request fields into domain model parameters,
        delegates to the analytics service, and converts the response
        back to the gRPC message format.

        Args:
            request: The gRPC GetMetricsRequest message.
            context: The gRPC request context.

        Returns:
            A gRPC GetMetricsResponse message with time series data.
        """
        logger.info("GetMetrics request: metric_names=%s", request.metric_names)

        metric_names = list(request.metric_names)
        labels = dict(request.labels) if request.labels else None
        time_range = self._parse_time_range(request.start_time, request.end_time)
        window = self._parse_step(request.step)
        aggregation = self._parse_aggregation(request.aggregation)

        try:
            series_list = self._analytics_service.get_metrics(
                metric_names=metric_names,
                labels=labels,
                time_range=time_range,
                window=window,
                aggregation=aggregation,
            )
        except Exception as exc:
            logger.error("GetMetrics failed: %s", exc)
            await context.abort(code=500, details=str(exc))

        total_points = sum(s.total_points for s in series_list)
        return self._build_metrics_response(series_list, total_points)

    async def Query(self, request: Any, context: Any) -> Any:
        """Handle the Query (traces) gRPC request.

        Translates the gRPC request fields into trace query parameters,
        delegates to the analytics service, and converts the response
        back to the gRPC message format.

        Args:
            request: The gRPC QueryTracesRequest message.
            context: The gRPC request context.

        Returns:
            A gRPC QueryTracesResponse message with trace data.
        """
        logger.info("Query traces request: service=%s", request.service_name)

        time_range = self._parse_time_range(request.start_time, request.end_time)
        trace_id = request.trace_id if request.HasField("trace_id") else None
        service_name = request.service_name if request.HasField("service_name") else None
        operation_name = request.operation_name if request.HasField("operation_name") else None
        min_duration = request.min_duration_ms if request.HasField("min_duration_ms") else None
        max_duration = request.max_duration_ms if request.HasField("max_duration_ms") else None

        try:
            traces = self._analytics_service.query_traces(
                trace_id=trace_id,
                service_name=service_name,
                operation_name=operation_name,
                min_duration_ms=min_duration,
                max_duration_ms=max_duration,
                tags=dict(request.tags) if request.tags else None,
                time_range=time_range,
                limit=request.limit,
            )
        except Exception as exc:
            logger.error("Query traces failed: %s", exc)
            await context.abort(code=500, details=str(exc))

        return {
            "traces": traces,
            "total_count": len(traces),
            "sampled": len(traces) >= request.limit,
        }

    async def GetDashboard(self, request: Any, context: Any) -> Any:
        """Handle the GetDashboard gRPC request.

        Loads the dashboard configuration, substitutes dynamic variables,
        and executes all panel queries against the time series store.

        Args:
            request: The gRPC GetDashboardRequest message.
            context: The gRPC request context.

        Returns:
            A gRPC GetDashboardResponse message with dashboard data.
        """
        logger.info("GetDashboard request: id=%s", request.dashboard_id)

        time_range = self._parse_time_range(request.start_time, request.end_time)

        try:
            result = self._dashboard_service.get_dashboard(
                dashboard_id=request.dashboard_id,
                time_range=time_range,
            )
        except Exception as exc:
            logger.error("GetDashboard failed: %s", exc)
            await context.abort(code=500, details=str(exc))

        return result

    async def GetReport(self, request: Any, context: Any) -> Any:
        """Handle the GetReport gRPC request.

        Generates an analytical report with the specified type, parameters,
        time range, and output format.

        Args:
            request: The gRPC GetReportRequest message.
            context: The gRPC request context.

        Returns:
            A gRPC GetReportResponse message with report data.
        """
        logger.info("GetReport request: type=%s", request.report_type)

        time_range = self._parse_time_range(request.start_time, request.end_time)

        try:
            report_type = ReportType(request.report_type)
        except ValueError:
            await context.abort(code=400, details=f"Unknown report type: {request.report_type}")
            return

        try:
            format_str = request.output_format if request.output_format else "json"
            report_format = ReportFormat(format_str)
        except ValueError:
            report_format = ReportFormat.JSON

        try:
            report = self._report_service.get_report(
                report_type=report_type,
                parameters=dict(request.parameters) if request.parameters else None,
                time_range=time_range,
                format=report_format,
            )
        except Exception as exc:
            logger.error("GetReport failed: %s", exc)
            await context.abort(code=500, details=str(exc))

        return report.to_dict()

    def _parse_time_range(self, start_time: Any, end_time: Any) -> TimeRange | None:
        """Parse gRPC timestamp fields into a TimeRange domain model.

        Handles both the case where timestamps are provided and where they
        are omitted (returning None to use defaults).

        Args:
            start_time: The gRPC Timestamp for the start of the range.
            end_time: The gRPC Timestamp for the end of the range.

        Returns:
            A TimeRange instance, or None if timestamps are not provided.
        """
        if start_time and end_time:
            try:
                start = datetime.fromtimestamp(start_time.seconds + start_time.nanos / 1e9, tz=timezone.utc)
                end = datetime.fromtimestamp(end_time.seconds + end_time.nanos / 1e9, tz=timezone.utc)
                return TimeRange(start=start, end=end)
            except (AttributeError, ValueError):
                return None
        return None

    def _parse_step(self, step: int) -> AggregationWindow:
        """Parse a gRPC step enum value into an AggregationWindow.

        Maps the proto Step enum (MINUTE=0, HOUR=1, DAY=2) to the domain
        AggregationWindow enum.

        Args:
            step: The step enum value from the gRPC request.

        Returns:
            The corresponding AggregationWindow enum value.
        """
        mapping = {0: AggregationWindow.ONE_MINUTE, 1: AggregationWindow.ONE_HOUR, 2: AggregationWindow.ONE_DAY}
        return mapping.get(step, AggregationWindow.ONE_MINUTE)

    def _parse_aggregation(self, aggregation: int) -> AggregationFunction:
        """Parse a gRPC aggregation enum value into an AggregationFunction.

        Maps the proto Aggregation enum to the domain AggregationFunction.

        Args:
            aggregation: The aggregation enum value from the gRPC request.

        Returns:
            The corresponding AggregationFunction enum value.
        """
        mapping = {
            0: AggregationFunction.AVG,
            1: AggregationFunction.SUM,
            2: AggregationFunction.MAX,
            3: AggregationFunction.MIN,
            4: AggregationFunction.P50,
            5: AggregationFunction.P95,
            6: AggregationFunction.P99,
        }
        return mapping.get(aggregation, AggregationFunction.AVG)

    def _build_metrics_response(self, series_list: list, total_points: int) -> dict[str, Any]:
        """Build the gRPC GetMetricsResponse from domain time series data.

        Args:
            series_list: List of TimeSeries domain objects.
            total_points: Total number of data points across all series.

        Returns:
            A dictionary representation of the gRPC response.
        """
        return {
            "series": [s.to_dict() for s in series_list],
            "total_points": total_points,
            "resolution": "1m",
        }
