"""
Notification entity and related value objects.

This module defines the core Notification entity along with the enumerations
and value objects that describe a notification's lifecycle. The Notification
entity is the aggregate root for the notification delivery domain, tracking
the complete state from creation through delivery confirmation.

The status transitions follow a strict state machine: PENDING -> QUEUED ->
SENDING -> SENT -> DELIVERED (or FAILED / BOUNCED along the way). Each
transition is validated to prevent illegal state changes such as moving from
FAILED back to SENDING without an explicit retry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class NotificationChannel(Enum):
    """Supported notification delivery channels.

    Each channel corresponds to a distinct delivery provider adapter. The
    channel determines how the rendered template content is formatted and
    which external service is used for delivery. New channels can be added
    here without modifying existing channel adapters, following the open/
    closed principle.
    """

    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WEBHOOK = "webhook"


class NotificationStatus(Enum):
    """Lifecycle states for a notification.

    The status represents where the notification is in the delivery pipeline.
    PENDING indicates the notification has been created but not yet queued.
    QUEUED means it is scheduled for delivery. SENDING indicates the delivery
    provider has been invoked. SENT confirms the provider accepted the message.
    DELIVERED means the recipient's device confirmed receipt. FAILED and
    BOUNCED represent terminal error states after all retries are exhausted.
    """

    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"


class NotificationPriority(Enum):
    """Priority levels controlling delivery behavior.

    URGENT and HIGH priority notifications bypass the ML delivery optimization
    model and are sent immediately, regardless of quiet hours. NORMAL and LOW
    priority notifications are subject to delivery time optimization and quiet
    hour deferral. Priority also affects retry behavior: higher priority
    notifications receive more aggressive retry schedules.
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationType(Enum):
    """Categorization of notification content.

    The notification type determines which template is used, which delivery
    rules apply, and whether the notification can be suppressed by recipient
    preferences. Transactional types (ORDER_CONFIRMATION, PAYMENT_RECEIVED,
    SHIPPING_UPDATE) cannot be fully opted out of, while promotional and
    system alert types respect the recipient's channel preferences.
    """

    ORDER_CONFIRMATION = "order_confirmation"
    ORDER_CANCELLATION = "order_cancellation"
    ORDER_DELIVERY = "order_delivery"
    PAYMENT_RECEIPT = "payment_receipt"
    PAYMENT_REFUND = "payment_refund"
    PAYMENT_FAILURE = "payment_failure"
    INVENTORY_ALERT = "inventory_alert"
    PROMOTIONAL = "promotional"
    SYSTEM_ALERT = "system_alert"


@dataclass(frozen=True)
class Recipient:
    """Value object representing the notification recipient.

    The recipient carries both the internal user identifier and the channel-
    specific address information needed for delivery. The user_id is used for
    preference lookups and correlation, while the email, phone, device_token,
    and webhook_url fields provide the actual delivery addresses. At least one
    channel address must be provided for the recipient to be reachable.
    """

    user_id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    device_token: Optional[str] = None
    webhook_url: Optional[str] = None
    timezone: str = "UTC"

    def has_channel_address(self, channel: NotificationChannel) -> bool:
        """Check whether this recipient has an address for the given channel.

        This method is used by the channel router to determine whether a
        notification can be delivered to this recipient through the specified
        channel before attempting to invoke the delivery provider.
        """
        channel_address_map = {
            NotificationChannel.EMAIL: self.email,
            NotificationChannel.SMS: self.phone,
            NotificationChannel.PUSH: self.device_token,
            NotificationChannel.WEBHOOK: self.webhook_url,
        }
        return channel_address_map.get(channel) is not None


@dataclass
class Notification:
    """Core notification aggregate root.

    The Notification entity tracks the complete lifecycle of a notification
    from creation through delivery confirmation. It enforces state transition
    rules and provides methods for recording delivery attempts and tracking
    events. The correlation_id links the notification to the originating
    domain event for end-to-end traceability across service boundaries.

    The entity uses a list of tracking events to maintain a complete audit
    trail of delivery status changes. This event history supports both
    operational debugging and the ML model's training data pipeline.
    """

    notification_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recipient: Optional[Recipient] = None
    channel: Optional[NotificationChannel] = None
    notification_type: Optional[NotificationType] = None
    priority: NotificationPriority = NotificationPriority.NORMAL
    status: NotificationStatus = NotificationStatus.PENDING
    template_id: Optional[str] = None
    template_vars: dict[str, str] = field(default_factory=dict)
    subject: Optional[str] = None
    body: Optional[str] = None
    correlation_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    retry_count: int = 0
    max_retries: int = 3
    tracking_events: list[TrackingEvent] = field(default_factory=list)

    # Forward reference resolved at runtime
    from .delivery import TrackingEvent

    def transition_to(self, new_status: NotificationStatus) -> None:
        """Transition the notification to a new status with validation.

        This method enforces the state machine rules for notification status
        transitions. Illegal transitions raise ValueError to prevent the
        notification from entering an inconsistent state. Valid transitions
        follow the pipeline: PENDING -> QUEUED -> SENDING -> SENT -> DELIVERED,
        with FAILED and BOUNCED reachable from SENDING.
        """
        valid_transitions: dict[NotificationStatus, set[NotificationStatus]] = {
            NotificationStatus.PENDING: {NotificationStatus.QUEUED, NotificationStatus.FAILED},
            NotificationStatus.QUEUED: {NotificationStatus.SENDING, NotificationStatus.FAILED},
            NotificationStatus.SENDING: {NotificationStatus.SENT, NotificationStatus.FAILED, NotificationStatus.BOUNCED},
            NotificationStatus.SENT: {NotificationStatus.DELIVERED, NotificationStatus.BOUNCED, NotificationStatus.FAILED},
            NotificationStatus.DELIVERED: set(),
            NotificationStatus.FAILED: {NotificationStatus.QUEUED},  # retry
            NotificationStatus.BOUNCED: set(),
        }

        allowed = valid_transitions.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition from {self.status.value} "
                f"to {new_status.value}"
            )

        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)

    def is_retryable(self) -> bool:
        """Check whether this notification can be retried.

        A notification is retryable if it is in a FAILED state and has not
        exceeded the maximum retry count. Bounced notifications are not
        retryable because the bounce indicates a permanent delivery failure
        such as an invalid email address.
        """
        return (
            self.status == NotificationStatus.FAILED
            and self.retry_count < self.max_retries
        )

    def increment_retry(self) -> None:
        """Increment the retry counter and transition back to QUEUED.

        This method is called when a delivery attempt fails transiently and
        the notification should be re-queued for another attempt. It validates
        that the notification is in a retryable state before incrementing the
        counter and transitioning the status.
        """
        if not self.is_retryable():
            raise ValueError("Notification is not retryable")
        self.retry_count += 1
        self.transition_to(NotificationStatus.QUEUED)

    def is_high_priority(self) -> bool:
        """Check if this notification has high or urgent priority.

        High-priority notifications bypass the ML delivery optimization model
        and quiet hour restrictions. They are sent immediately through the
        fastest available channel to ensure timely delivery.
        """
        return self.priority in (NotificationPriority.HIGH, NotificationPriority.URGENT)
