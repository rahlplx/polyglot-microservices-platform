"""
Pydantic Settings configuration for the Notification service.

This module defines the service configuration using Pydantic's BaseSettings,
which loads configuration from environment variables with type validation and
default values. The configuration is organized into logical groups: server,
database, Kafka, delivery providers, and observability.

Configuration values can be overridden through environment variables, which
is the standard approach for containerized deployments. The settings class
supports .env files for local development.
"""

from __future__ import annotations

from typing import Optional

import logging

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class ServerConfig(BaseSettings):
    """HTTP and gRPC server configuration.

    Controls the ports, TLS settings, and worker configuration for
    the FastAPI HTTP server and the gRPC query server. The HTTP
    server handles webhook callbacks and administrative queries,
    while the gRPC server handles synchronous queries from the
    Gateway service.
    """

    http_host: str = Field(default="0.0.0.0", description="HTTP server bind address")
    http_port: int = Field(default=8080, description="HTTP server port")
    grpc_port: int = Field(default=9090, description="gRPC server port")
    workers: int = Field(default=4, description="Number of worker processes")
    enable_cors: bool = Field(default=True, description="Enable CORS for HTTP server")
    # SECURITY: CORS origins must be explicitly configured in production.
    # An empty default ensures no origins are allowed unless explicitly
    # specified via the SERVER_CORS_ORIGINS environment variable.
    # A wildcard "*" is rejected in production environments (see validator below).
    cors_origins: list[str] = Field(
        default=[],
        description="Allowed CORS origins (must be explicitly set; wildcards rejected in production)",
    )
    request_timeout_seconds: int = Field(
        default=30, description="HTTP request timeout"
    )

    @model_validator(mode="after")
    def _validate_cors_origins(self) -> "ServerConfig":
        """Warn if wildcard CORS origins are detected."""
        if "*" in self.cors_origins:
            logger.warning(
                "CORS wildcard detected in SERVER_CORS_ORIGINS. "
                "Wildcard origins are insecure and should not be used in production."
            )
        return self

    model_config = {"env_prefix": "SERVER_"}


class DatabaseConfig(BaseSettings):
    """PostgreSQL database configuration.

    Controls the connection string, pool size, and migration settings
    for the SQLAlchemy async database adapter. The connection string
    uses the asyncpg driver for non-blocking database operations.

    SECURITY: The database URL contains credentials and MUST be provided
    via the DB_URL environment variable. No default is provided to prevent
    hardcoded credentials from leaking into source control.
    """

    url: str = Field(
        default="",
        description="Async PostgreSQL connection string (MUST be set via DB_URL env var)",
    )
    pool_size: int = Field(default=20, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max overflow connections")
    pool_pre_ping: bool = Field(default=True, description="Enable connection health checks")
    echo_sql: bool = Field(default=False, description="Log SQL statements")
    run_migrations: bool = Field(default=True, description="Run Alembic migrations on startup")

    @model_validator(mode="after")
    def _validate_db_url(self) -> "DatabaseConfig":
        """Warn if the database URL is not configured."""
        if not self.url:
            msg = (
                "DB_URL is not set. The database URL MUST be provided via the "
                "DB_URL environment variable (e.g. "
                "postgresql+asyncpg://user:pass@host:5432/db). "
                "The service will fail to connect to the database."
            )
            logger.critical(msg)
            raise ValueError(msg)
        return self

    model_config = {"env_prefix": "DB_"}


class KafkaConfig(BaseSettings):
    """Apache Kafka configuration.

    Controls the bootstrap servers, consumer group, and topic
    configuration for the event consumer and producer. The consumer
    uses a cooperative-sticky partition assignment strategy for
    balanced consumption across multiple service instances.
    """

    bootstrap_servers: str = Field(
        default="localhost:9092",
        description="Kafka bootstrap servers",
    )
    consumer_group_id: str = Field(
        default="notification-event-consumer",
        description="Consumer group identifier",
    )
    auto_offset_reset: str = Field(
        default="earliest",
        description="Offset reset strategy (earliest/latest)",
    )
    enable_auto_commit: bool = Field(
        default=False,
        description="Enable automatic offset commits",
    )
    session_timeout_ms: int = Field(
        default=30000,
        description="Consumer session timeout in milliseconds",
    )
    max_poll_interval_ms: int = Field(
        default=300000,
        description="Maximum poll interval in milliseconds",
    )
    concurrency_limit: int = Field(
        default=20,
        description="Maximum concurrent notification processing tasks",
    )
    max_retries: int = Field(
        default=3,
        description="Maximum retry attempts for failed events",
    )
    dlq_topic: str = Field(
        default="notification.events.dlq",
        description="Dead letter topic for permanently failed events",
    )
    produced_topics: list[str] = Field(
        default=[
            "com.company.notification.sent",
            "com.company.notification.delivered",
            "com.company.notification.opened",
            "com.company.notification.failed",
        ],
        description="Topics for produced notification lifecycle events",
    )

    model_config = {"env_prefix": "KAFKA_"}


class EmailProviderConfig(BaseSettings):
    """Email delivery provider configuration.

    Supports both SMTP and Amazon SES as email delivery providers.
    When SES is configured, the adapter routes through the ACL sidecar
    for vendor SDK isolation and circuit breaking.
    """

    provider: str = Field(default="smtp", description="Email provider (smtp/ses)")
    smtp_host: str = Field(default="localhost", description="SMTP server host")
    smtp_port: int = Field(default=587, description="SMTP server port")
    smtp_username: Optional[str] = Field(default=None, description="SMTP username")
    smtp_password: Optional[str] = Field(default=None, description="SMTP password")
    use_tls: bool = Field(default=True, description="Use TLS for SMTP")
    from_address: str = Field(
        default="notifications@company.com",
        description="Sender email address",
    )
    from_name: str = Field(
        default="Notification Service",
        description="Sender display name",
    )
    ses_endpoint: Optional[str] = Field(
        default=None, description="Amazon SES API endpoint"
    )

    model_config = {"env_prefix": "EMAIL_"}


class SmsProviderConfig(BaseSettings):
    """SMS delivery provider configuration.

    Supports both Twilio and Amazon SNS as SMS delivery providers.
    All external communication routes through the ACL sidecar.
    """

    provider: str = Field(default="twilio", description="SMS provider (twilio/sns)")
    from_number: str = Field(
        default="+15551234567",
        description="Sender phone number",
    )
    twilio_account_sid: Optional[str] = Field(
        default=None, description="Twilio account SID"
    )
    twilio_auth_token: Optional[str] = Field(
        default=None, description="Twilio auth token"
    )
    sns_region: str = Field(default="us-east-1", description="AWS SNS region")

    model_config = {"env_prefix": "SMS_"}


class PushProviderConfig(BaseSettings):
    """Push notification provider configuration.

    Supports Firebase Cloud Messaging (FCM) for Android/web and
    Apple Push Notification service (APNs) for iOS.
    """

    fcm_project_id: Optional[str] = Field(
        default=None, description="Google Cloud project ID for FCM"
    )
    fcm_service_account_key: Optional[str] = Field(
        default=None, description="Path to FCM service account key"
    )
    apns_cert_path: Optional[str] = Field(
        default=None, description="Path to APNs certificate"
    )
    apns_key_id: Optional[str] = Field(
        default=None, description="APNs authentication key ID"
    )
    apns_team_id: Optional[str] = Field(
        default=None, description="Apple developer team ID"
    )

    model_config = {"env_prefix": "PUSH_"}


class WebhookConfig(BaseSettings):
    """Webhook delivery configuration.

    Controls the HTTP timeout, retry behavior, and request signing
    for webhook notifications.
    """

    default_timeout: int = Field(default=30, description="HTTP request timeout")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    base_backoff_seconds: float = Field(
        default=1.0, description="Initial exponential backoff interval"
    )
    max_backoff_seconds: float = Field(
        default=60.0, description="Maximum backoff interval cap"
    )
    signing_secret: Optional[str] = Field(
        default=None, description="HMAC-SHA256 signing secret"
    )

    model_config = {"env_prefix": "WEBHOOK_"}


class ObservabilityConfig(BaseSettings):
    """OpenTelemetry observability configuration.

    Controls the OTLP exporter endpoint and auto-instrumentation
    settings for distributed tracing and metrics collection.
    """

    enabled: bool = Field(default=True, description="Enable OpenTelemetry")
    otlp_endpoint: Optional[str] = Field(
        default=None, description="OTLP collector endpoint URL"
    )
    service_name: str = Field(
        default="notification-service",
        description="OTel service name",
    )
    service_version: str = Field(
        default="0.1.0", description="OTel service version"
    )
    enable_auto_instrumentation: bool = Field(
        default=True, description="Enable auto-instrumentation"
    )
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="json", description="Log format (json/text)"
    )

    model_config = {"env_prefix": "OTEL_"}


class ACLSidecarConfig(BaseSettings):
    """ACL sidecar configuration for external provider communication.

    The ACL sidecar provides circuit breaking, rate limiting, and
    vendor SDK isolation for all external service communication.
    """

    enabled: bool = Field(default=False, description="Enable ACL sidecar routing")
    url: str = Field(
        default="http://localhost:8081",
        description="ACL sidecar base URL",
    )

    model_config = {"env_prefix": "ACL_"}


class NotificationServiceConfig(BaseSettings):
    """Root configuration for the Notification service.

    Aggregates all sub-configurations into a single object that is
    injected through the dependency injection container. Environment
    variables are loaded from .env files for local development and
    from the container environment for production deployments.
    """

    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    kafka: KafkaConfig = Field(default_factory=KafkaConfig)
    email: EmailProviderConfig = Field(default_factory=EmailProviderConfig)
    sms: SmsProviderConfig = Field(default_factory=SmsProviderConfig)
    push: PushProviderConfig = Field(default_factory=PushProviderConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    acl: ACLSidecarConfig = Field(default_factory=ACLSidecarConfig)

    app_name: str = Field(
        default="notification-service",
        description="Application name",
    )
    environment: str = Field(
        default="development",
        description="Deployment environment",
    )
    debug: bool = Field(default=False, description="Enable debug mode")

    @model_validator(mode="after")
    def _validate_production_cors(self) -> "NotificationServiceConfig":
        """SECURITY: Reject wildcard CORS origins in production environments.

        Allowing '*' in CORS origins permits any origin to make cross-origin
        requests, which is unacceptable in production. Origins must be
        explicitly enumerated via the SERVER_CORS_ORIGINS env var.
        """
        if self.environment == "production" and "*" in self.server.cors_origins:
            msg = (
                "CORS wildcard '*' is not allowed in production. "
                "Explicitly set SERVER_CORS_ORIGINS to a list of "
                "trusted origin URLs (e.g. 'https://app.example.com,https://admin.example.com')."
            )
            logger.critical(msg)
            raise ValueError(msg)
        return self
