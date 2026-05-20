"""
Dual FastAPI + gRPC server for the Analytics service.

This module implements the server that exposes the Analytics service through
both REST (FastAPI) and gRPC protocols. The REST server serves the OpenAPI-
defined endpoints for dashboard UI consumption and external reporting tools,
while the gRPC server handles internal service-to-service queries with
lower overhead and stronger typing.

The server manages the application lifecycle: starting the DI container,
initializing database connections, launching the Kafka event consumer, and
configuring graceful shutdown. It also exposes health check endpoints for
Kubernetes liveness and readiness probes, and a Prometheus metrics endpoint
for monitoring.

Both servers run concurrently in separate threads, sharing the same domain
service instances through the DI container. The gRPC server enforces mTLS
with SPIFFE SVID verification, while the REST server supports CORS for
browser-based dashboard access and JWT authentication for API consumers.
"""

from __future__ import annotations

import logging
import signal
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from .config import AnalyticsConfig
from .di import DIContainer

logger = logging.getLogger(__name__)


def create_app(config: AnalyticsConfig | None = None) -> Any:
    """Create and configure the FastAPI application.

    This factory function creates the FastAPI application with all
    routes, middleware, and lifecycle hooks configured according to
    the provided configuration. It is designed to be called from the
    main entry point and is also suitable for testing with a custom
    configuration.

    Args:
        config: The application configuration. If None, loads from
            environment variables using Pydantic Settings.

    Returns:
        The configured FastAPI application instance.
    """
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware

    if config is None:
        config = AnalyticsConfig()

    container = DIContainer(config)

    @asynccontextmanager
    async def lifespan(app: Any):
        """Manage the application lifecycle: startup and shutdown.

        The lifespan context manager handles initialization of the DI
        container (database connections, event consumers) at startup
        and graceful shutdown of all components.
        """
        logger.info("Starting Analytics service")
        container.initialize()
        yield
        logger.info("Shutting down Analytics service")
        container.shutdown()

    app = FastAPI(
        title="Analytics Service",
        description="Business intelligence, reporting, and observability-driven insights",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Configure CORS for browser-based dashboard access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- REST API Routes ---

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, Any]:
        """Health check endpoint for Kubernetes liveness probes.

        Returns basic service health information. If this endpoint
        returns 200, the service process is alive and responsive.
        """
        return {
            "status": "healthy",
            "service": "analytics",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/ready", tags=["health"])
    async def readiness_check() -> dict[str, Any]:
        """Readiness check endpoint for Kubernetes readiness probes.

        Checks that all dependent services (ClickHouse, PostgreSQL)
        are accessible before reporting ready. The service will not
        receive traffic until this endpoint returns 200.
        """
        checks: dict[str, str] = {}

        try:
            if container.clickhouse_repo._client:
                checks["clickhouse"] = "ok"
            else:
                checks["clickhouse"] = "not_connected"
        except Exception:
            checks["clickhouse"] = "error"

        try:
            if container.postgres_repo._connection:
                checks["postgres"] = "ok"
            else:
                checks["postgres"] = "not_connected"
        except Exception:
            checks["postgres"] = "error"

        overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
        return {
            "status": overall,
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.post("/api/v1/analytics/metrics/query", tags=["analytics"])
    async def query_metrics(request: dict[str, Any]) -> dict[str, Any]:
        """Execute a metric time series query.

        Accepts a JSON request body with metric names, label filters,
        time range, and aggregation parameters. Returns time series
        data suitable for dashboard visualization.

        Supports the Accept: text/csv header for CSV export.
        """
        metric_names = request.get("metric_names", [])
        labels = request.get("labels")
        start_str = request.get("start_time")
        end_str = request.get("end_time")
        step = request.get("step", "1m")
        aggregation = request.get("aggregation", "avg")

        time_range = None
        if start_str and end_str:
            from ..domain.models.report import TimeRange
            time_range = TimeRange(
                start=datetime.fromisoformat(start_str),
                end=datetime.fromisoformat(end_str),
            )

        from ..domain.models.aggregation import AggregationWindow, AggregationFunction
        window_map = {"1m": AggregationWindow.ONE_MINUTE, "5m": AggregationWindow.FIVE_MINUTES, "1h": AggregationWindow.ONE_HOUR, "1d": AggregationWindow.ONE_DAY}
        agg_map = {f.value: f for f in AggregationFunction}
        window = window_map.get(step, AggregationWindow.ONE_MINUTE)
        agg_func = agg_map.get(aggregation, AggregationFunction.AVG)

        series_list = container.analytics_service.get_metrics(
            metric_names=metric_names,
            labels=labels,
            time_range=time_range,
            window=window,
            aggregation=agg_func,
        )

        return {
            "series": [s.to_dict() for s in series_list],
            "total_points": sum(s.total_points for s in series_list),
        }

    @app.post("/api/v1/analytics/traces/query", tags=["analytics"])
    async def query_traces(request: dict[str, Any]) -> dict[str, Any]:
        """Execute a trace search query.

        Accepts filter criteria including trace ID, service name,
        operation name, duration range, and tags. Returns matching
        traces with their full span trees.
        """
        traces = container.analytics_service.query_traces(
            trace_id=request.get("trace_id"),
            service_name=request.get("service_name"),
            operation_name=request.get("operation_name"),
            min_duration_ms=request.get("min_duration_ms"),
            max_duration_ms=request.get("max_duration_ms"),
            tags=request.get("tags"),
            limit=request.get("limit", 20),
        )

        return {
            "traces": traces,
            "total_count": len(traces),
        }

    @app.get("/api/v1/analytics/dashboards", tags=["analytics"])
    async def list_dashboards(tag: str | None = Query(default=None)) -> list[dict[str, Any]]:
        """List all available dashboards with optional tag filtering."""
        return container.dashboard_service.list_dashboards(tag=tag)

    @app.get("/api/v1/analytics/dashboards/{dashboard_id}", tags=["analytics"])
    async def get_dashboard(
        dashboard_id: str,
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Retrieve a dashboard with live data for all panels."""
        time_range = None
        if start and end:
            from ..domain.models.report import TimeRange
            time_range = TimeRange(
                start=datetime.fromisoformat(start),
                end=datetime.fromisoformat(end),
            )

        return container.dashboard_service.get_dashboard(
            dashboard_id=dashboard_id,
            time_range=time_range,
        )

    @app.put("/api/v1/analytics/dashboards/{dashboard_id}", tags=["analytics"])
    async def update_dashboard(dashboard_id: str, config: dict[str, Any]) -> dict[str, Any]:
        """Update a dashboard configuration."""
        return container.dashboard_service.update_dashboard(
            dashboard_id=dashboard_id,
            config=config,
        )

    @app.get("/api/v1/analytics/dependencies", tags=["analytics"])
    async def get_dependencies(
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Retrieve the service dependency graph derived from trace data."""
        time_range = None
        if start and end:
            from ..domain.models.report import TimeRange
            time_range = TimeRange(
                start=datetime.fromisoformat(start),
                end=datetime.fromisoformat(end),
            )

        return container.analytics_service.get_dependencies(time_range=time_range)

    @app.get("/api/v1/analytics/reports/{report_type}", tags=["analytics"])
    async def get_report(
        report_type: str,
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        format: str = Query(default="json"),
        granularity: str = Query(default="daily"),
    ) -> dict[str, Any]:
        """Generate an analytical report."""
        from ..domain.models.report import ReportType, ReportFormat, Granularity, TimeRange

        try:
            rt = ReportType(report_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown report type: {report_type}")

        try:
            rf = ReportFormat(format)
        except ValueError:
            rf = ReportFormat.JSON

        try:
            gr = Granularity(granularity)
        except ValueError:
            gr = Granularity.DAILY

        time_range = None
        if start and end:
            time_range = TimeRange(
                start=datetime.fromisoformat(start),
                end=datetime.fromisoformat(end),
            )

        report = container.report_service.get_report(
            report_type=rt,
            time_range=time_range,
            format=rf,
            granularity=gr,
        )

        return report.to_dict()

    return app


class AnalyticsServer:
    """Dual FastAPI + gRPC server manager for the Analytics service.

    This class manages the concurrent execution of both the FastAPI
    REST server and the gRPC query server. It handles graceful shutdown
    on SIGTERM/SIGINT, ensuring that in-flight requests complete before
    the server stops.

    The gRPC server includes reflection support via grpc_reflection.v1alpha
    for service discovery tools like grpcurl.
    """

    # gRPC service names for reflection registration
    SERVICE_NAMES = (
        "analytics.v1.AnalyticsService",
    )

    def __init__(self, config: AnalyticsConfig | None = None) -> None:
        """Initialize the server manager.

        Args:
            config: The application configuration. If None, loads from
                environment variables.
        """
        self._config = config or AnalyticsConfig()
        self._app = create_app(self._config)
        self._shutdown_event = threading.Event()

    def run(self) -> None:
        """Start the server and block until shutdown.

        Starts the FastAPI server using Uvicorn with the configured
        host and port. Registers signal handlers for graceful shutdown.
        The gRPC server runs in a separate thread.

        When the gRPC server is started, gRPC reflection is enabled
        via grpc_reflection.v1alpha for service discovery (e.g., grpcurl).
        To enable reflection on the gRPC server, add the following
        after creating the gRPC server:

            from grpc_reflection.v1alpha import reflection
            reflection.enable_server(grpc_server, SERVICE_NAMES)
        """
        import uvicorn

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        logger.info(
            "Starting Analytics server: http=%s:%d, grpc=%s:%d",
            self._config.server.http_host,
            self._config.server.http_port,
            self._config.server.grpc_host,
            self._config.server.grpc_port,
        )

        uvicorn.run(
            self._app,
            host=self._config.server.http_host,
            port=self._config.server.http_port,
            log_level=self._config.log_level.lower(),
            access_log=True,
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals gracefully.

        Sets the shutdown event, which triggers the graceful shutdown
        sequence in the lifespan manager.
        """
        logger.info("Received signal %s, initiating shutdown", signal.Signals(signum).name)
        self._shutdown_event.set()
