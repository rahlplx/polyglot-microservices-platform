"""
Dependency injection container for the Notification service.

This module wires together all the components of the notification service:
domain services, outbound port adapters, and inbound adapters. The
container follows the Composition Root pattern, creating all dependencies
in a single location and injecting them where needed.

The container is responsible for creating adapter instances with the
correct configuration and ensuring that the domain layer only depends
on port interfaces. It also manages the lifecycle of shared resources
such as database connections and Kafka consumers.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..domain.models.notification import NotificationChannel
from ..domain.ports.outbound.channel_sender import ChannelSenderPort
from ..domain.ports.outbound.delivery_tracker import DeliveryTrackerPort
from ..domain.ports.outbound.template_store import TemplateRepositoryPort
from ..domain.ports.outbound.preference_store import PreferenceRepositoryPort
from ..domain.services.delivery_optimizer import DeliveryOptimizer
from ..domain.services.notification_service import NotificationService
from ..domain.services.preference_service import PreferenceService
from ..domain.services.template_service import TemplateService
from ..adapters.inbound.event_consumer import EventConsumer
from ..adapters.inbound.grpc_handler import GrpcNotificationHandler
from ..adapters.outbound.channels.email_sender import EmailSenderAdapter
from ..adapters.outbound.channels.sms_sender import SmsSenderAdapter
from ..adapters.outbound.channels.push_sender import PushSenderAdapter
from ..adapters.outbound.channels.webhook_sender import WebhookSenderAdapter
from ..adapters.outbound.persistence.notification_repo import NotificationRepository
from ..adapters.outbound.persistence.template_repo import TemplateRepositoryAdapter
from ..adapters.outbound.preferences.preference_repo import PreferenceRepositoryAdapter
from ..adapters.outbound.observability.otel import OTelInstrumentation
from .config import NotificationServiceConfig

logger = logging.getLogger(__name__)


class DIContainer:
    """Dependency injection container for the Notification service.

    The container creates and manages the lifecycle of all service
    components, wiring together domain services with their adapter
    implementations. It ensures that each component receives its
    dependencies through constructor injection, following the
    Dependency Inversion Principle.

    The container is initialized once during service startup and
    provides access to all components through typed properties.
    Components are created lazily on first access to support
    testing scenarios where only specific components are needed.

    The gRPC server includes reflection support via grpc_reflection.v1alpha
    for service discovery tools like grpcurl. Enable it with:
        from grpc_reflection.v1alpha import reflection
        reflection.enable_server(grpc_server, SERVICE_NAMES)
    """

    # gRPC service names for reflection registration
    SERVICE_NAMES = (
        "notification.v1.NotificationService",
    )

    def __init__(self, config: Optional[NotificationServiceConfig] = None) -> None:
        """Initialize the DI container with configuration.

        Args:
            config: The service configuration. If None, default
                configuration is used (suitable for development).
        """
        self._config = config or NotificationServiceConfig()
        self._notification_repo: Optional[NotificationRepository] = None
        self._template_repo: Optional[TemplateRepositoryAdapter] = None
        self._preference_repo: Optional[PreferenceRepositoryAdapter] = None
        self._channel_senders: Optional[dict[NotificationChannel, ChannelSenderPort]] = None
        self._delivery_optimizer: Optional[DeliveryOptimizer] = None
        self._template_service: Optional[TemplateService] = None
        self._preference_service: Optional[PreferenceService] = None
        self._notification_service: Optional[NotificationService] = None
        self._event_consumer: Optional[EventConsumer] = None
        self._grpc_handler: Optional[GrpcNotificationHandler] = None
        self._otel: Optional[OTelInstrumentation] = None

    @property
    def config(self) -> NotificationServiceConfig:
        """The service configuration."""
        return self._config

    @property
    def otel(self) -> OTelInstrumentation:
        """The OpenTelemetry instrumentation adapter."""
        if self._otel is None:
            self._otel = OTelInstrumentation(
                service_name=self._config.observability.service_name,
                service_version=self._config.observability.service_version,
                otlp_endpoint=self._config.observability.otlp_endpoint,
                enable_auto_instrumentation=self._config.observability.enable_auto_instrumentation,
            )
        return self._otel

    @property
    def notification_repo(self) -> NotificationRepository:
        """The notification persistence repository."""
        if self._notification_repo is None:
            self._notification_repo = NotificationRepository(
                database_url=self._config.database.url,
            )
        return self._notification_repo

    @property
    def template_repo(self) -> TemplateRepositoryAdapter:
        """The template persistence repository."""
        if self._template_repo is None:
            self._template_repo = TemplateRepositoryAdapter()
            self._template_repo.seed_default_templates()
        return self._template_repo

    @property
    def preference_repo(self) -> PreferenceRepositoryAdapter:
        """The preference persistence repository."""
        if self._preference_repo is None:
            self._preference_repo = PreferenceRepositoryAdapter()
        return self._preference_repo

    @property
    def channel_senders(self) -> dict[NotificationChannel, ChannelSenderPort]:
        """Map of notification channels to their sender adapters."""
        if self._channel_senders is None:
            acl_url = self._config.acl.url if self._config.acl.enabled else None

            email_sender = EmailSenderAdapter(
                smtp_host=self._config.email.smtp_host,
                smtp_port=self._config.email.smtp_port,
                smtp_username=self._config.email.smtp_username,
                smtp_password=self._config.email.smtp_password,
                use_tls=self._config.email.use_tls,
                from_address=self._config.email.from_address,
                from_name=self._config.email.from_name,
                ses_endpoint=self._config.email.ses_endpoint,
                acl_sidecar_url=acl_url,
            )

            sms_sender = SmsSenderAdapter(
                provider=self._config.sms.provider,
                from_number=self._config.sms.from_number,
                twilio_account_sid=self._config.sms.twilio_account_sid,
                twilio_auth_token=self._config.sms.twilio_auth_token,
                sns_region=self._config.sms.sns_region,
                acl_sidecar_url=acl_url,
            )

            push_sender = PushSenderAdapter(
                fcm_project_id=self._config.push.fcm_project_id,
                fcm_service_account_key=self._config.push.fcm_service_account_key,
                apns_cert_path=self._config.push.apns_cert_path,
                apns_key_id=self._config.push.apns_key_id,
                apns_team_id=self._config.push.apns_team_id,
                acl_sidecar_url=acl_url,
            )

            webhook_sender = WebhookSenderAdapter(
                default_timeout=self._config.webhook.default_timeout,
                max_retries=self._config.webhook.max_retries,
                base_backoff_seconds=self._config.webhook.base_backoff_seconds,
                max_backoff_seconds=self._config.webhook.max_backoff_seconds,
                signing_secret=self._config.webhook.signing_secret,
                acl_sidecar_url=acl_url,
            )

            self._channel_senders = {
                NotificationChannel.EMAIL: email_sender,
                NotificationChannel.SMS: sms_sender,
                NotificationChannel.PUSH: push_sender,
                NotificationChannel.WEBHOOK: webhook_sender,
            }
        return self._channel_senders

    @property
    def delivery_optimizer(self) -> DeliveryOptimizer:
        """The ML delivery optimization service."""
        if self._delivery_optimizer is None:
            self._delivery_optimizer = DeliveryOptimizer()
        return self._delivery_optimizer

    @property
    def template_service(self) -> TemplateService:
        """The template rendering service."""
        if self._template_service is None:
            self._template_service = TemplateService(
                template_repo=self.template_repo,
            )
        return self._template_service

    @property
    def preference_service(self) -> PreferenceService:
        """The preference management service."""
        if self._preference_service is None:
            self._preference_service = PreferenceService(
                preference_repo=self.preference_repo,
            )
        return self._preference_service

    @property
    def notification_service(self) -> NotificationService:
        """The core notification orchestration service."""
        if self._notification_service is None:
            self._notification_service = NotificationService(
                delivery_tracker=self.notification_repo,
                template_repo=self.template_repo,
                preference_repo=self.preference_repo,
                channel_senders=self.channel_senders,
                delivery_optimizer=self.delivery_optimizer,
                template_service=self.template_service,
                preference_service=self.preference_service,
            )
        return self._notification_service

    @property
    def event_consumer(self) -> EventConsumer:
        """The Kafka CloudEvent consumer adapter."""
        if self._event_consumer is None:
            self._event_consumer = EventConsumer(
                notification_service=self.notification_service,
                kafka_config={
                    "bootstrap.servers": self._config.kafka.bootstrap_servers,
                },
                max_retries=self._config.kafka.max_retries,
                concurrency_limit=self._config.kafka.concurrency_limit,
                dlq_topic=self._config.kafka.dlq_topic,
            )
        return self._event_consumer

    @property
    def grpc_handler(self) -> GrpcNotificationHandler:
        """The gRPC query handler adapter."""
        if self._grpc_handler is None:
            self._grpc_handler = GrpcNotificationHandler(
                status_port=self.notification_service,
                preferences_port=self.notification_service,
            )
        return self._grpc_handler

    async def initialize(self) -> None:
        """Initialize all container-managed resources.

        Creates database tables, seeds default data, and starts
        background services. This method should be called during
        service startup.
        """
        logger.info("Initializing DI container...")

        # Initialize OpenTelemetry
        if self._config.observability.enabled:
            self.otel.initialize()

        # Initialize database
        await self.notification_repo.initialize()

        # Seed default templates
        self.template_repo.seed_default_templates()

        logger.info("DI container initialized successfully")

    async def shutdown(self) -> None:
        """Gracefully shutdown all container-managed resources.

        Closes database connections, stops background consumers, and
        flushes telemetry data. This method should be called during
        service shutdown.
        """
        logger.info("Shutting down DI container...")

        # Stop event consumer
        if self._event_consumer:
            self._event_consumer.stop()

        # Close database connections
        if self._notification_repo:
            await self._notification_repo.close()

        # Shutdown OTel
        if self._otel:
            self._otel.shutdown()

        logger.info("DI container shutdown complete")
