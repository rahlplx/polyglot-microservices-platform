"""
Domain models for the Notification service.

These models represent the core business concepts of notification delivery,
including notification entities, delivery status tracking, channel preferences,
and template rendering. All models are pure Python dataclasses with zero
external dependencies, ensuring the hexagonal architecture boundary is
respected. The models use Python 3.12+ type hints for maximum clarity.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class NotificationChannel(str, Enum):
    """Supported notification delivery channels.
    Each channel has different delivery characteristics, latency profiles,
    and cost structures that affect the delivery optimization algorithm."""
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"
    WEBHOOK = "WEBHOOK"


class NotificationStatus(str, Enum):
    """Lifecycle states for a notification.
    Notifications follow QUEUED → SENDING → SENT → DELIVERED, with
    possible transitions to FAILED at any point before DELIVERED."""
    QUEUED = "QUEUED"
    SENDING = "SENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class NotificationPriority(str, Enum):
    """Priority levels that affect delivery ordering and channel selection.
    CRITICAL notifications bypass quiet hours and rate limits. HIGH
    notifications bypass quiet hours but respect rate limits. NORMAL
    and LOW notifications respect all preference constraints."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


@dataclass(frozen=True)
class Money:
    """Value object for monetary amounts, using int cents to avoid float errors.
    This mirrors the Payment service's Money type for consistency across
    the microservices architecture, though the Notification service uses
    it primarily for cost tracking and billing calculations."""
    amount_cents: int
    currency: str = "USD"


@dataclass
class Notification:
    """Core notification entity representing a single notification to be delivered.
    Each notification has a unique ID, target recipient, channel preference,
    content payload, and delivery status. The entity tracks the full lifecycle
    from creation through delivery, including retry attempts and failures."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recipient_id: str = ""
    channel: NotificationChannel = NotificationChannel.EMAIL
    status: NotificationStatus = NotificationStatus.QUEUED
    priority: NotificationPriority = NotificationPriority.NORMAL
    subject: str = ""
    body: str = ""
    html_body: str = ""
    template_id: Optional[str] = None
    template_vars: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    delivery_attempts: int = 0
    max_attempts: int = 3
    idempotency_key: Optional[str] = None

    def can_send(self) -> bool:
        """Check if the notification is in a state that allows sending.
        Only QUEUED notifications can be sent. FAILED notifications with
        remaining attempts are re-queued rather than sent directly."""
        return self.status in (NotificationStatus.QUEUED,)

    def can_retry(self) -> bool:
        """Check if a failed notification can be retried.
        Retries are limited by max_attempts to prevent infinite loops
        when a channel is persistently unavailable."""
        return self.status == NotificationStatus.FAILED and self.delivery_attempts < self.max_attempts

    def mark_sending(self) -> None:
        """Transition the notification to SENDING state."""
        if self.status != NotificationStatus.QUEUED:
            raise ValueError(f"Cannot send notification in {self.status} state")
        self.status = NotificationStatus.SENDING
        self.delivery_attempts += 1

    def mark_sent(self) -> None:
        """Transition the notification to SENT state after successful channel delivery."""
        self.status = NotificationStatus.SENT
        self.sent_at = datetime.now(timezone.utc)

    def mark_delivered(self) -> None:
        """Transition the notification to DELIVERED state after channel confirmation."""
        self.status = NotificationStatus.DELIVERED
        self.delivered_at = datetime.now(timezone.utc)

    def mark_failed(self, reason: str = "") -> None:
        """Transition the notification to FAILED state with an optional reason.
        Failed notifications may be retried if attempts remain."""
        self.status = NotificationStatus.FAILED
        self.metadata["failure_reason"] = reason


@dataclass
class DeliveryAttempt:
    """Tracks a single delivery attempt for observability and debugging.
    Each attempt records the channel, timestamp, outcome, and any error
    details. This history supports the ML delivery optimizer in learning
    which channels work best for each recipient at different times."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    notification_id: str = ""
    channel: NotificationChannel = NotificationChannel.EMAIL
    attempted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = False
    error_message: str = ""
    response_time_ms: float = 0.0
    provider_id: Optional[str] = None


@dataclass
class NotificationPreference:
    """User preferences for notification delivery.
    Controls which channels are enabled, quiet hours, and delivery
    rate limits. Preferences are checked before every send attempt
    to respect user communication boundaries."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    email_enabled: bool = True
    sms_enabled: bool = True
    push_enabled: bool = True
    webhook_enabled: bool = False
    quiet_hours_start: Optional[str] = None  # HH:MM format, e.g., "22:00"
    quiet_hours_end: Optional[str] = None    # HH:MM format, e.g., "08:00"
    quiet_hours_timezone: str = "UTC"
    max_daily_notifications: int = 50
    digest_mode: bool = False  # Batch notifications into daily digest
    preferred_channel: NotificationChannel = NotificationChannel.EMAIL


@dataclass
class Template:
    """Notification template with Jinja2-compatible content placeholders.
    Templates support both plain text and HTML variants, with variable
    substitution at render time. Templates are versioned to support
    A/B testing and gradual rollout of new notification designs."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    subject_template: str = ""    # Jinja2 template for subject
    body_template: str = ""       # Jinja2 template for plain text body
    html_template: str = ""       # Jinja2 template for HTML body
    channel: NotificationChannel = NotificationChannel.EMAIL
    version: int = 1
    active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
