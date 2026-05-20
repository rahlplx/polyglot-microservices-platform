"""
Domain ports (interfaces) for the Notification service.

Ports define the boundaries of the hexagonal architecture. Inbound ports
are use case interfaces called by driving adapters (gRPC handlers, Kafka
consumers). Outbound ports are infrastructure interfaces implemented by
driven adapters (email senders, SMS gateways, databases). All ports use
Python Protocol or ABC to define contracts without implementation details.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import (
    DeliveryAttempt, Notification, NotificationChannel,
    NotificationPreference, NotificationStatus, Template,
)


# === Inbound Ports (Use Cases) ===

class SendNotificationPort(ABC):
    """Primary use case for sending notifications through the delivery pipeline.
    This port coordinates preference checking, template rendering, channel
    selection, and delivery tracking. It is the main entry point for all
    notification creation, whether from gRPC requests or Kafka events."""

    @abstractmethod
    async def send(self, notification: Notification) -> Notification:
        """Process and send a notification through the optimal channel.
        Returns the updated notification with delivery status."""
        ...

    @abstractmethod
    async def send_batch(self, notifications: list[Notification]) -> list[Notification]:
        """Process and send multiple notifications in batch.
        Batch sending optimizes channel rate limiting and throughput."""
        ...


class GetDeliveryStatusPort(ABC):
    """Use case for querying notification delivery status and history.
    Supports both individual notification lookup and filtered listing
    for the admin dashboard and customer-facing status pages."""

    @abstractmethod
    async def get_status(self, notification_id: str) -> Optional[Notification]:
        """Retrieve a notification by its unique identifier."""
        ...

    @abstractmethod
    async def get_attempts(self, notification_id: str) -> list[DeliveryAttempt]:
        """Retrieve all delivery attempts for a notification."""
        ...


class GetPreferencesPort(ABC):
    """Use case for managing user notification preferences.
    Preferences control channel opt-in/out, quiet hours, and
    rate limits that the delivery optimizer must respect."""

    @abstractmethod
    async def get_preferences(self, user_id: str) -> Optional[NotificationPreference]:
        """Retrieve notification preferences for a user."""
        ...

    @abstractmethod
    async def update_preferences(self, prefs: NotificationPreference) -> NotificationPreference:
        """Update notification preferences for a user."""
        ...


# === Outbound Ports (Infrastructure Interfaces) ===

class ChannelSenderPort(ABC):
    """Interface for sending notifications through a specific channel.
    Each channel (email, SMS, push, webhook) implements this interface
    independently, allowing the domain to remain channel-agnostic.
    All channel implementations run behind the ACL boundary for
    external service communication."""

    @abstractmethod
    async def send(self, notification: Notification) -> DeliveryAttempt:
        """Send a notification through this channel.
        Returns a DeliveryAttempt with the outcome and timing details."""
        ...

    @abstractmethod
    def supports_channel(self, channel: NotificationChannel) -> bool:
        """Check if this sender supports the given channel type."""
        ...


class NotificationRepositoryPort(ABC):
    """Interface for persisting and querying notification records.
    Implementations use SQLAlchemy async with PostgreSQL for production
    and in-memory dicts for testing."""

    @abstractmethod
    async def save(self, notification: Notification) -> Notification:
        """Persist a notification record."""
        ...

    @abstractmethod
    async def get_by_id(self, notification_id: str) -> Optional[Notification]:
        """Retrieve a notification by ID."""
        ...

    @abstractmethod
    async def get_by_idempotency_key(self, key: str) -> Optional[Notification]:
        """Retrieve a notification by its idempotency key."""
        ...

    @abstractmethod
    async def update(self, notification: Notification) -> Notification:
        """Update an existing notification record."""
        ...

    @abstractmethod
    async def list_by_recipient(
        self, recipient_id: str, status: Optional[NotificationStatus] = None,
        limit: int = 50, offset: int = 0,
    ) -> list[Notification]:
        """List notifications for a recipient with optional status filter."""
        ...


class TemplateRepositoryPort(ABC):
    """Interface for managing notification templates.
    Templates are versioned documents with Jinja2 placeholders
    that are rendered at send time with context variables."""

    @abstractmethod
    async def get_by_id(self, template_id: str) -> Optional[Template]:
        """Retrieve a template by its unique identifier."""
        ...

    @abstractmethod
    async def get_by_name(self, name: str, version: Optional[int] = None) -> Optional[Template]:
        """Retrieve a template by name and optional version."""
        ...


class PreferenceRepositoryPort(ABC):
    """Interface for persisting and querying user preferences.
    Preferences are read before every send attempt to ensure
    user communication boundaries are always respected."""

    @abstractmethod
    async def get_by_user_id(self, user_id: str) -> Optional[NotificationPreference]:
        """Retrieve preferences for a specific user."""
        ...

    @abstractmethod
    async def save(self, prefs: NotificationPreference) -> NotificationPreference:
        """Persist user notification preferences."""
        ...


class DeliveryTrackerPort(ABC):
    """Interface for tracking delivery attempts and outcomes.
    The tracker feeds data into the ML delivery optimizer to improve
    future delivery timing and channel selection decisions."""

    @abstractmethod
    async def record_attempt(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        """Record a delivery attempt with timing and outcome."""
        ...

    @abstractmethod
    async def get_channel_stats(self, channel: NotificationChannel, hours: int = 168) -> dict:
        """Get delivery statistics for a channel over the given time window.
        Returns success rate, average latency, and per-hour open rates."""
        ...
