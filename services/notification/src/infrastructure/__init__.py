"""
Infrastructure layer for the Notification service.

Contains configuration, dependency injection, identity management,
and server setup. This layer wires together all adapters and services,
creating the composition root for the hexagonal architecture.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from ..domain.ports import (
    ChannelSenderPort, DeliveryTrackerPort, NotificationRepositoryPort,
    PreferenceRepositoryPort, TemplateRepositoryPort,
)
from ..domain.services import DeliveryOptimizer, NotificationService
from ..adapters.inbound import GrpcHandler, KafkaEventConsumer
from ..adapters.outbound import EmailSender, PushSender, SmsSender, WebhookSender


@dataclass
class Config:
    """Service configuration loaded from environment variables.
    Each value has a sensible default for local development.
    Production values are injected via Kubernetes ConfigMaps and Secrets."""
    grpc_port: int = int(os.getenv("NOTIFICATION_GRPC_PORT", "50056"))
    http_port: int = int(os.getenv("NOTIFICATION_HTTP_PORT", "8086"))
    metrics_port: int = int(os.getenv("NOTIFICATION_METRICS_PORT", "9096"))
    kafka_brokers: str = os.getenv("NOTIFICATION_KAFKA_BROKERS", "localhost:9092")
    kafka_group_id: str = os.getenv("NOTIFICATION_KAFKA_GROUP_ID", "notification-service")
    kafka_topics: str = os.getenv("NOTIFICATION_KAFKA_TOPICS", "order.events,payment.events")
    db_host: str = os.getenv("NOTIFICATION_DB_HOST", "localhost")
    db_port: int = int(os.getenv("NOTIFICATION_DB_PORT", "5432"))
    db_name: str = os.getenv("NOTIFICATION_DB_NAME", "notification")
    db_user: str = os.getenv("NOTIFICATION_DB_USER", "notification")
    db_password: str = os.getenv("NOTIFICATION_DB_PASSWORD", "")
    smtp_host: str = os.getenv("NOTIFICATION_SMTP_HOST", "localhost")
    smtp_port: int = int(os.getenv("NOTIFICATION_SMTP_PORT", "587"))
    otel_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
    spiffe_enabled: bool = os.getenv("SPIFFE_ENABLED", "false").lower() == "true"
    spiffe_trust_domain: str = os.getenv("SPIFFE_TRUST_DOMAIN", "gstack.dev")


class Container:
    """Dependency injection container for the Notification service.
    Follows the composition root pattern — all concrete implementations
    are created here and injected as interfaces. This manual DI approach
    keeps the dependency graph explicit and testable."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config()

        # Outbound adapters.
        self.notification_repo: NotificationRepositoryPort = InMemoryNotificationRepo()
        self.template_repo: TemplateRepositoryPort = InMemoryTemplateRepo()
        self.preference_repo: PreferenceRepositoryPort = InMemoryPreferenceRepo()
        self.delivery_tracker: DeliveryTrackerPort = InMemoryDeliveryTracker()
        self.channel_senders: list[ChannelSenderPort] = [
            EmailSender(), SmsSender(), PushSender(), WebhookSender(),
        ]

        # Domain services.
        self.delivery_optimizer = DeliveryOptimizer(self.delivery_tracker)
        self.notification_service = NotificationService(
            notification_repo=self.notification_repo,
            template_repo=self.template_repo,
            preference_repo=self.preference_repo,
            channel_senders=self.channel_senders,
            delivery_tracker=self.delivery_tracker,
            delivery_optimizer=self.delivery_optimizer,
        )

        # Inbound adapters.
        self.grpc_handler = GrpcHandler(self.notification_service)
        self.kafka_consumer = KafkaEventConsumer(self.notification_service)


# In-memory implementations for development and testing.

class InMemoryNotificationRepo(NotificationRepositoryPort):
    def __init__(self) -> None:
        self._store: dict[str, Notification] = {}
        self._idempotency: dict[str, str] = {}

    async def save(self, notification: Notification) -> Notification:
        self._store[notification.id] = notification
        if notification.idempotency_key:
            self._idempotency[notification.idempotency_key] = notification.id
        return notification

    async def get_by_id(self, notification_id: str) -> Optional[Notification]:
        return self._store.get(notification_id)

    async def get_by_idempotency_key(self, key: str) -> Optional[Notification]:
        nid = self._idempotency.get(key)
        return self._store.get(nid) if nid else None

    async def update(self, notification: Notification) -> Notification:
        self._store[notification.id] = notification
        return notification

    async def list_by_recipient(self, recipient_id: str, status=None, limit=50, offset=0) -> list:
        return [n for n in self._store.values() if n.recipient_id == recipient_id][:limit]


class InMemoryTemplateRepo(TemplateRepositoryPort):
    def __init__(self) -> None:
        self._store: dict[str, Template] = {}

    async def get_by_id(self, template_id: str) -> Optional[Template]:
        return self._store.get(template_id)

    async def get_by_name(self, name: str, version=None) -> Optional[Template]:
        for t in self._store.values():
            if t.name == name and (version is None or t.version == version):
                return t
        return None


class InMemoryPreferenceRepo(PreferenceRepositoryPort):
    def __init__(self) -> None:
        self._store: dict[str, NotificationPreference] = {}

    async def get_by_user_id(self, user_id: str) -> Optional[NotificationPreference]:
        return self._store.get(user_id)

    async def save(self, prefs: NotificationPreference) -> NotificationPreference:
        self._store[prefs.user_id] = prefs
        return prefs


class InMemoryDeliveryTracker(DeliveryTrackerPort):
    def __init__(self) -> None:
        self._attempts: list[DeliveryAttempt] = []

    async def record_attempt(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        self._attempts.append(attempt)
        return attempt

    async def get_channel_stats(self, channel, hours=168) -> dict:
        channel_attempts = [a for a in self._attempts if a.channel == channel]
        if not channel_attempts:
            return {"success_rate": 0.0, "avg_latency_ms": 0.0}
        successes = sum(1 for a in channel_attempts if a.success)
        avg_latency = sum(a.response_time_ms for a in channel_attempts) / len(channel_attempts)
        return {"success_rate": successes / len(channel_attempts), "avg_latency_ms": avg_latency}


# Need these imports at runtime for type annotations above
from ..domain.models import DeliveryAttempt, Notification, NotificationPreference, Template  # noqa: E402
