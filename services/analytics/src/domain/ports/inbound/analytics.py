"""
Analytics inbound port definitions for the Analytics service.

This module defines the four primary inbound ports that constitute the
service's public API: GetMetrics, QueryTraces, GetDashboard, and GetReport.
Each port is expressed as a Python Protocol, enabling structural subtyping
so that the domain layer does not depend on concrete implementations.

These ports are the contract between the domain services and the inbound
adapters (gRPC handlers, REST controllers). Any adapter that wishes to
expose analytics capabilities must implement these port interfaces or
delegate to domain services that implement them.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models.aggregation import AggregationFunction, AggregationWindow
from ..models.metric import TimeSeries
from ..models.report import Granularity, Report, ReportFormat, ReportType, TimeRange


@runtime_checkable
class GetMetricsPort(Protocol):
    """Port for retrieving aggregated metric time series data.

    This port supports querying multiple metric names in a single request,
    with optional label selectors for dimensional filtering. The time range
    is specified with start and end timestamps, and the step parameter
    controls the granularity of the returned data points. When the requested
    time range exceeds the retention period for raw data, the implementation
    automatically falls back to pre-aggregated rollup tables.
    """

    def get_metrics(
        self,
        metric_names: list[str],
        labels: dict[str, str] | None = None,
        time_range: TimeRange | None = None,
        window: AggregationWindow = AggregationWindow.ONE_MINUTE,
        aggregation: AggregationFunction = AggregationFunction.AVG,
    ) -> list[TimeSeries]:
        """Retrieve aggregated time series data for the specified metrics.

        Args:
            metric_names: List of metric identifiers to query.
            labels: Optional label selectors for dimensional filtering.
            time_range: The temporal scope of the query.
            window: The aggregation window size for data point granularity.
            aggregation: The function used to combine data points within each window.

        Returns:
            A list of TimeSeries, one per requested metric name, each
            containing data points at the specified window interval.

        Raises:
            MetricNotFoundError: If any requested metric name does not exist.
            InvalidTimeRangeError: If the time range is malformed or too broad.
            AggregationNotSupportedError: If the aggregation function is not
                available for the requested metric type.
        """
        ...


@runtime_checkable
class QueryTracesPort(Protocol):
    """Port for querying distributed traces for debugging and performance analysis.

    This port supports multiple query modes: direct trace lookup by trace ID,
    service-based search, and operation-based search. Tag-based filtering
    allows searching for traces with specific attributes such as error status
    or high latency. The port includes a safeguard against overly broad queries
    that would scan excessive data.
    """

    def query_traces(
        self,
        trace_id: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
        tags: dict[str, str] | None = None,
        time_range: TimeRange | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search distributed traces based on various criteria.

        Args:
            trace_id: Optional trace ID for direct lookup.
            service_name: Optional service name filter.
            operation_name: Optional operation name filter.
            min_duration_ms: Optional minimum duration filter in milliseconds.
            max_duration_ms: Optional maximum duration filter in milliseconds.
            tags: Optional tag-based filters.
            time_range: The temporal scope of the search.
            limit: Maximum number of traces to return.

        Returns:
            A list of trace dictionaries, each containing the full span tree
            with parent-child relationships preserved.

        Raises:
            TraceStorageUnavailableError: If the trace storage backend is down.
            QueryTooBroadError: If the query would scan too much data.
        """
        ...


@runtime_checkable
class GetDashboardPort(Protocol):
    """Port for retrieving pre-configured dashboards with live data.

    Dashboards are configuration objects that specify panels, each containing
    a metric query, visualization type, and display options. This port
    executes all panel queries in parallel and returns the dashboard
    definition along with the populated data. Dashboards are cached for
    30 seconds to reduce database load during frequent refresh cycles.
    """

    def get_dashboard(
        self,
        dashboard_id: str,
        variables: dict[str, str] | None = None,
        time_range: TimeRange | None = None,
    ) -> dict:
        """Retrieve a dashboard with live data for all panels.

        Args:
            dashboard_id: The unique identifier of the dashboard configuration.
            variables: Optional dynamic variables for query customization.
            time_range: The temporal scope for all panel queries.

        Returns:
            A dictionary containing the dashboard definition and populated
            data for each panel.

        Raises:
            DashboardNotFoundError: If the dashboard ID does not exist.
            VariableValidationError: If a variable value is invalid.
            DataFetchError: If one or more panel queries fail.
        """
        ...


@runtime_checkable
class GetReportPort(Protocol):
    """Port for generating analytical reports with configurable parameters.

    Reports are predefined analytical templates that encapsulate complex
    multi-metric queries into structured outputs suitable for business
    stakeholders. Each report type includes a specific set of metrics,
    dimensions, and visualizations. Report generation is asynchronous
    for large time ranges, returning a report ID that can be polled for
    completion status. Generated reports are cached for 5 minutes.
    """

    def get_report(
        self,
        report_type: ReportType,
        parameters: dict[str, str] | None = None,
        time_range: TimeRange | None = None,
        format: ReportFormat = ReportFormat.JSON,
        granularity: Granularity = Granularity.DAILY,
    ) -> Report:
        """Generate a pre-configured analytical report.

        Args:
            report_type: The type of report to generate.
            parameters: Optional parameters for dynamic customization.
            time_range: The temporal scope of the report data.
            format: The output format (JSON, CSV, or PDF).
            granularity: The temporal resolution of report data points.

        Returns:
            A Report object containing the generated data and metadata.

        Raises:
            ReportTypeNotFoundError: If the report type is not recognized.
            InsufficientDataError: If there is not enough data for the
                requested time range.
            ReportGenerationTimeoutError: If report generation exceeds the
                time limit.
        """
        ...
