"""
Infrastructure layer for the Analytics service.

Contains configuration, dependency injection, identity management,
and server setup for the analytics subsystem.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from ..domain.ports import (
    DashboardRepositoryPort, EventRepositoryPort, TimeSeriesRepositoryPort,
)
from ..domain.services import AggregationService, AnalyticsService, DashboardService, ReportService
from ..adapters.inbound import GrpcHandler, KafkaEventConsumer
from ..adapters.outbound import (
    ClickHouseTimeSeriesRepo, PostgresDashboardRepo, PostgresEventRepo,
)


@dataclass
class Config:
    """Service configuration loaded from environment variables."""
    grpc_port: int = int(os.getenv("ANALYTICS_GRPC_PORT", "50057"))
    http_port: int = int(os.getenv("ANALYTICS_HTTP_PORT", "8087"))
    metrics_port: int = int(os.getenv("ANALYTICS_METRICS_PORT", "9097"))
    kafka_brokers: str = os.getenv("ANALYTICS_KAFKA_BROKERS", "localhost:9092")
    kafka_group_id: str = os.getenv("ANALYTICS_KAFKA_GROUP_ID", "analytics-service")
    kafka_topics: str = os.getenv("ANALYTICS_KAFKA_TOPICS", "order.events,payment.events,otel-spans")
    clickhouse_dsn: str = os.getenv("ANALYTICS_CLICKHOUSE_DSN", "clickhouse://localhost:9000")
    db_host: str = os.getenv("ANALYTICS_DB_HOST", "localhost")
    db_port: int = int(os.getenv("ANALYTICS_DB_PORT", "5432"))
    db_name: str = os.getenv("ANALYTICS_DB_NAME", "analytics")
    db_user: str = os.getenv("ANALYTICS_DB_USER", "analytics")
    db_password: str = os.getenv("ANALYTICS_DB_PASSWORD", "")
    otel_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
    spiffe_enabled: bool = os.getenv("SPIFFE_ENABLED", "false").lower() == "true"


class Container:
    """Dependency injection container for the Analytics service."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config()

        # Outbound adapters.
        self.ts_repo: TimeSeriesRepositoryPort = ClickHouseTimeSeriesRepo(self.config.clickhouse_dsn)
        self.event_repo: EventRepositoryPort = PostgresEventRepo()
        self.dashboard_repo: DashboardRepositoryPort = PostgresDashboardRepo()

        # Domain services.
        self.aggregation_service = AggregationService(self.ts_repo)
        self.analytics_service = AnalyticsService(self.ts_repo, self.event_repo, self.aggregation_service)
        self.report_service = ReportService(self.ts_repo)
        self.dashboard_service = DashboardService(self.ts_repo, self.event_repo)

        # Inbound adapters.
        self.grpc_handler = GrpcHandler(self.analytics_service, self.dashboard_service, self.report_service)
        self.kafka_consumer = KafkaEventConsumer(self.analytics_service)
