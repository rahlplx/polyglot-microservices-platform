"""
Pydantic Settings configuration for the Analytics service.

This module defines the application configuration using Pydantic BaseSettings,
which automatically reads values from environment variables and .env files.
The configuration is validated at startup, ensuring that all required settings
are present and correctly formatted before the service begins processing
requests.

Configuration is organized into logical groups: server settings for the
FastAPI and gRPC servers, ClickHouse settings for the time series store,
PostgreSQL settings for the event/metadata store, Kafka settings for the
event consumer, OTel settings for self-instrumentation, and SPIFFE settings
for mTLS identity. Each group can be configured independently, supporting
flexible deployment across development, staging, and production environments.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


class ServerSettings(BaseSettings):
    """HTTP and gRPC server configuration.

    These settings control the FastAPI REST server and the gRPC query
    server. The REST server serves the OpenAPI-defined endpoints for
    dashboard UI consumption, while the gRPC server handles internal
    service-to-service queries.
    """

    http_host: str = Field(default="0.0.0.0", description="HTTP server bind address")
    http_port: int = Field(default=8080, description="HTTP server port")
    grpc_host: str = Field(default="0.0.0.0", description="gRPC server bind address")
    grpc_port: int = Field(default=50057, description="gRPC server port")
    otlp_port: int = Field(default=4317, description="OTLP receiver port")
    workers: int = Field(default=4, description="Number of worker processes")
    cors_origins: list[str] = Field(
        default=["*"],
        description="Allowed CORS origins for the REST API",
    )
    request_timeout_seconds: int = Field(default=30, description="Request timeout in seconds")

    model_config = {"env_prefix": "ANALYTICS_SERVER_"}


class ClickHouseSettings(BaseSettings):
    """ClickHouse time series database configuration.

    These settings control the connection to the ClickHouse cluster
    that stores all metric time series data and pre-computed rollups.
    The adapter uses the clickhouse-connect driver with native protocol
    support for maximum write throughput.
    """

    host: str = Field(default="localhost", description="ClickHouse server hostname")
    port: int = Field(default=8123, description="ClickHouse HTTP interface port")
    database: str = Field(default="analytics", description="Database name")
    username: str = Field(default="default", description="Authentication username")
    password: str = Field(default="", description="Authentication password")
    connect_timeout: int = Field(default=10, description="Connection timeout in seconds")
    write_buffer_size: int = Field(default=10000, description="Write buffer size before flushing")

    model_config = {"env_prefix": "ANALYTICS_CLICKHOUSE_"}


class PostgresSettings(BaseSettings):
    """PostgreSQL event/metadata store configuration.

    These settings control the connection to the PostgreSQL instance
    that stores dashboard configurations, event metadata, alert rules,
    and transformer registry configurations.
    """

    host: str = Field(default="localhost", description="PostgreSQL hostname")
    port: int = Field(default=5432, description="PostgreSQL port")
    database: str = Field(default="analytics", description="Database name")
    username: str = Field(default="analytics", description="Authentication username")
    password: str = Field(default="analytics", description="Authentication password")
    pool_size: int = Field(default=5, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max overflow connections")

    @property
    def connection_string(self) -> str:
        """Build the SQLAlchemy connection string from component settings.

        Returns:
            A postgresql:// connection string.
        """
        return (
            f"postgresql://{self.username}:{self.password}@"
            f"{self.host}:{self.port}/{self.database}"
        )

    model_config = {"env_prefix": "ANALYTICS_POSTGRES_"}


class KafkaSettings(BaseSettings):
    """Apache Kafka event consumer configuration.

    These settings control the Kafka consumer that ingests domain events
    from the event backbone. The consumer subscribes to all com.company.*
    topics using a topic pattern subscription.
    """

    bootstrap_servers: str = Field(default="localhost:9092", description="Kafka broker addresses")
    consumer_group: str = Field(default="analytics-event-consumer", description="Consumer group ID")
    topic_pattern: str = Field(default="com.company.*", description="Topic subscription pattern")
    batch_size: int = Field(default=10000, description="Events per batch before flushing")
    batch_timeout_seconds: float = Field(default=5.0, description="Seconds before flushing batch")
    max_retries: int = Field(default=3, description="Retry attempts for failed events")
    dlq_topic: str = Field(default="analytics.events.dlq", description="Dead letter topic")
    enable_auto_commit: bool = Field(default=False, description="Auto-commit consumer offsets")
    concurrency_limit: int = Field(default=50, description="Max concurrent event processing")

    model_config = {"env_prefix": "ANALYTICS_KAFKA_"}


class OTelSettings(BaseSettings):
    """OpenTelemetry self-instrumentation configuration.

    These settings control the OTel SDK configuration for the service's
    own telemetry. Self-monitoring metrics are exported to a separate
    endpoint to prevent feedback loops with the ingested telemetry.
    """

    enabled: bool = Field(default=True, description="Enable OTel instrumentation")
    endpoint: str = Field(default="http://localhost:4317", description="OTLP export endpoint")
    service_name: str = Field(default="analytics", description="OTel service name")
    service_version: str = Field(default="0.1.0", description="OTel service version")
    enable_tracing: bool = Field(default=True, description="Enable distributed tracing")
    enable_metrics: bool = Field(default=True, description="Enable metric collection")
    export_interval_seconds: int = Field(default=60, description="Metric export interval")

    model_config = {"env_prefix": "ANALYTICS_OTEL_"}


class SpiffeSettings(BaseSettings):
    """SPIFFE/SPIRE mTLS identity configuration.

    These settings control the SPIFFE workload API connection and
    X.509 SVID management for service-to-service mTLS authentication.
    """

    enabled: bool = Field(default=True, description="Enable SPIFFE mTLS")
    socket_path: str = Field(default="/run/spire/sockets/agent.sock", description="SPIRE agent socket")
    trust_domain: str = Field(default="com.company", description="SPIFFE trust domain")
    service_spiffe_id: str = Field(
        default="spiffe://com.company/analytics",
        description="SPIFFE ID for this service",
    )

    model_config = {"env_prefix": "ANALYTICS_SPIFFE_"}


class AnalyticsConfig(BaseSettings):
    """Root configuration for the Analytics service.

    Aggregates all configuration groups into a single object that is
    passed to the dependency injection container. The configuration
    is validated at startup, and any missing required settings will
    cause the service to fail fast with a clear error message.
    """

    server: ServerSettings = Field(default_factory=ServerSettings)
    clickhouse: ClickHouseSettings = Field(default_factory=ClickHouseSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    otel: OTelSettings = Field(default_factory=OTelSettings)
    spiffe: SpiffeSettings = Field(default_factory=SpiffeSettings)

    # Global settings
    log_level: str = Field(default="INFO", description="Logging level")
    environment: str = Field(default="development", description="Deployment environment")
    max_query_range_days: int = Field(default=90, description="Maximum query range in days")
    dashboard_cache_ttl: int = Field(default=30, description="Dashboard cache TTL in seconds")
    report_cache_ttl: int = Field(default=300, description="Report cache TTL in seconds")

    model_config = {"env_prefix": "ANALYTICS_"}
