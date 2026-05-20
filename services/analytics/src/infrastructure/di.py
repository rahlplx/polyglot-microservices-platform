"""
Dependency injection container for the Analytics service.

This module implements the DI container that wires together all domain
services with their required outbound port implementations. The container
is constructed at startup using the application configuration and manages
the lifecycle of all service instances, including database connections
and event consumers.

The container follows a simple construction pattern: it creates adapters
first (as they implement the outbound ports that domain services depend on),
then creates domain services with their adapter dependencies injected.
This ensures that all dependencies are satisfied before any service
starts processing requests.
"""

from __future__ import annotations

import logging

from ..domain.services.analytics_service import AnalyticsService
from ..domain.services.aggregation_service import AggregationService
from ..domain.services.dashboard_service import DashboardService
from ..domain.services.report_service import ReportService
from ..adapters.inbound.event_consumer import EventConsumer
from ..adapters.inbound.grpc_handler import GrpcHandler
from ..adapters.outbound.persistence.clickhouse_repo import ClickHouseTimeSeriesRepository
from ..adapters.outbound.persistence.postgres_repo import PostgresEventRepository
from ..adapters.outbound.processing.otel_span_processor import OTelSpanProcessor
from ..adapters.outbound.observability.otel import OtelInstrumentation
from .config import AnalyticsConfig

logger = logging.getLogger(__name__)


class DIContainer:
    """Dependency injection container for the Analytics service.

    This container manages the construction and lifecycle of all service
    components. It creates adapters (outbound port implementations) first,
    then injects them into domain services. The container also manages
    startup and shutdown sequences, ensuring that database connections
    are established before services start and closed gracefully on shutdown.
    """

    def __init__(self, config: AnalyticsConfig) -> None:
        """Initialize the DI container with the application configuration.

        Args:
            config: The root application configuration object.
        """
        self._config = config
        self._initialized = False

        # Outbound adapters
        self._clickhouse_repo: ClickHouseTimeSeriesRepository | None = None
        self._postgres_repo: PostgresEventRepository | None = None
        self._otel_processor: OTelSpanProcessor | None = None
        self._otel_instrumentation: OtelInstrumentation | None = None

        # Domain services
        self._analytics_service: AnalyticsService | None = None
        self._aggregation_service: AggregationService | None = None
        self._dashboard_service: DashboardService | None = None
        self._report_service: ReportService | None = None

        # Inbound adapters
        self._grpc_handler: GrpcHandler | None = None
        self._event_consumer: EventConsumer | None = None

    def initialize(self) -> None:
        """Initialize all service components in the correct dependency order.

        Outbound adapters are created first since domain services depend on
        them. Then domain services are created with their adapter dependencies
        injected. Finally, inbound adapters are created with their domain
        service dependencies. This ordering ensures that all dependencies
        are satisfied before any component starts processing.
        """
        if self._initialized:
            logger.warning("DI container already initialized")
            return

        logger.info("Initializing DI container")

        # 1. OTel self-instrumentation (must be first for tracing)
        self._otel_instrumentation = OtelInstrumentation(
            service_name=self._config.otel.service_name,
            service_version=self._config.otel.service_version,
            otlp_endpoint=self._config.otel.endpoint,
            enable_tracing=self._config.otel.enable_tracing,
            enable_metrics=self._config.otel.enable_metrics,
        )
        if self._config.otel.enabled:
            self._otel_instrumentation.setup()

        # 2. Outbound adapters
        self._clickhouse_repo = ClickHouseTimeSeriesRepository(
            host=self._config.clickhouse.host,
            port=self._config.clickhouse.port,
            database=self._config.clickhouse.database,
            username=self._config.clickhouse.username,
            password=self._config.clickhouse.password,
            connect_timeout=self._config.clickhouse.connect_timeout,
            write_buffer_size=self._config.clickhouse.write_buffer_size,
        )
        self._clickhouse_repo.connect()

        self._postgres_repo = PostgresEventRepository(
            connection_string=self._config.postgres.connection_string,
            pool_size=self._config.postgres.pool_size,
            max_overflow=self._config.postgres.max_overflow,
        )
        self._postgres_repo.connect()

        self._otel_processor = OTelSpanProcessor(
            time_series_repo=self._clickhouse_repo,
        )

        # 3. Domain services
        self._analytics_service = AnalyticsService(
            time_series_repo=self._clickhouse_repo,
            event_repo=self._postgres_repo,
            otel_processor=self._otel_processor,
            max_query_range_days=self._config.max_query_range_days,
        )

        self._aggregation_service = AggregationService(
            time_series_repo=self._clickhouse_repo,
        )

        self._dashboard_service = DashboardService(
            time_series_repo=self._clickhouse_repo,
            event_repo=self._postgres_repo,
            cache_ttl_seconds=self._config.dashboard_cache_ttl,
        )

        self._report_service = ReportService(
            time_series_repo=self._clickhouse_repo,
            event_repo=self._postgres_repo,
            cache_ttl_seconds=self._config.report_cache_ttl,
        )

        # 4. Inbound adapters
        self._grpc_handler = GrpcHandler(
            analytics_service=self._analytics_service,
            dashboard_service=self._dashboard_service,
            report_service=self._report_service,
        )

        self._event_consumer = EventConsumer(
            time_series_repo=self._clickhouse_repo,
            event_repo=self._postgres_repo,
            batch_size=self._config.kafka.batch_size,
            batch_timeout_seconds=self._config.kafka.batch_timeout_seconds,
            max_retries=self._config.kafka.max_retries,
            consumer_group=self._config.kafka.consumer_group,
        )

        self._initialized = True
        logger.info("DI container initialized successfully")

    def shutdown(self) -> None:
        """Gracefully shut down all service components in reverse order.

        Components are shut down in the reverse order of their creation
        to ensure that inbound adapters stop receiving requests before
        outbound adapters close their connections.
        """
        logger.info("Shutting down DI container")

        if self._event_consumer:
            self._event_consumer.stop()

        if self._clickhouse_repo:
            self._clickhouse_repo.disconnect()

        if self._postgres_repo:
            self._postgres_repo.disconnect()

        if self._otel_instrumentation:
            self._otel_instrumentation.shutdown()

        self._initialized = False
        logger.info("DI container shut down")

    @property
    def analytics_service(self) -> AnalyticsService:
        """Get the analytics query orchestration service."""
        assert self._analytics_service is not None, "Container not initialized"
        return self._analytics_service

    @property
    def aggregation_service(self) -> AggregationService:
        """Get the time-window aggregation service."""
        assert self._aggregation_service is not None, "Container not initialized"
        return self._aggregation_service

    @property
    def dashboard_service(self) -> DashboardService:
        """Get the dashboard configuration and data service."""
        assert self._dashboard_service is not None, "Container not initialized"
        return self._dashboard_service

    @property
    def report_service(self) -> ReportService:
        """Get the report generation and formatting service."""
        assert self._report_service is not None, "Container not initialized"
        return self._report_service

    @property
    def grpc_handler(self) -> GrpcHandler:
        """Get the gRPC query handler."""
        assert self._grpc_handler is not None, "Container not initialized"
        return self._grpc_handler

    @property
    def event_consumer(self) -> EventConsumer:
        """Get the Kafka event consumer."""
        assert self._event_consumer is not None, "Container not initialized"
        return self._event_consumer

    @property
    def clickhouse_repo(self) -> ClickHouseTimeSeriesRepository:
        """Get the ClickHouse time series repository."""
        assert self._clickhouse_repo is not None, "Container not initialized"
        return self._clickhouse_repo

    @property
    def postgres_repo(self) -> PostgresEventRepository:
        """Get the PostgreSQL event repository."""
        assert self._postgres_repo is not None, "Container not initialized"
        return self._postgres_repo

    @property
    def config(self) -> AnalyticsConfig:
        """Get the application configuration."""
        return self._config
