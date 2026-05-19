"""
Delivery tracking models for the notification pipeline.

This module defines the data structures used to track notification delivery
attempts, receipts, and tracking events. These models support the complete
delivery lifecycle: from the initial send attempt through provider callbacks
indicating delivery, open, click, bounce, or failure.

The tracking event system is designed to be append-only: events are recorded
as they arrive from delivery providers and are never modified or deleted.
This event sourcing approach provides a complete audit trail and supports
the ML delivery optimization model's training data requirements.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class DeliveryStatus(Enum):
    """Status of a delivery attempt from the provider's perspective.

    These statuses correspond to the feedback received from external delivery
    providers via webhook callbacks. They provide more granular information
    than the notification-level status, capturing the provider's view of the
    delivery outcome.
    """

    ACCEPTED = "accepted"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    FAILED = "failed"
    COMPLAINED = "complained"
    UNSUBSCRIBED = "unsubscribed"


class TrackingEventType(Enum):
    """Types of tracking events received from delivery providers.

    Each event type corresponds to a specific milestone in the delivery
    pipeline. Provider-specific event names are mapped to these canonical
    types by the webhook handler adapter, ensuring that the domain model
    remains independent of any particular provider's event taxonomy.
    """

    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    COMPLAINED = "complained"
    UNSUBSCRIBED = "unsubscribed"
    DEFERRED = "deferred"
    DROPPED = "dropped"


@dataclass(frozen=True)
class TrackingEvent:
    """Immutable record of a single tracking event from a delivery provider.

    Tracking events are append-only records that capture the delivery
    milestone, timestamp, and any provider-specific metadata. The event_id
    field is used for deduplication, as delivery providers may send the same
    event multiple times. The metadata field stores provider-specific data
    such as SMTP response codes, user agent strings, and IP addresses.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    notification_id: str = ""
    event_type: TrackingEventType = TrackingEventType.SENT
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    provider: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class DeliveryAttempt:
    """Record of a single delivery attempt for a notification.

    Each time the delivery provider is invoked, a DeliveryAttempt is created
    to record the outcome. This supports the retry mechanism: if the attempt
    fails transiently, the notification can be re-queued for another attempt.
    The attempt includes the channel used, the provider response, and any
    error information that could be useful for debugging.
    """

    attempt_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    notification_id: str = ""
    channel: str = ""
    provider: str = ""
    success: bool = False
    provider_message_id: Optional[str] = None
    error_message: Optional[str] = None
    attempted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    response_time_ms: Optional[int] = None

    def mark_success(self, provider_message_id: str, response_time_ms: int) -> None:
        """Record a successful delivery attempt.

        This method sets the success flag, records the provider's message
        identifier for tracking, and captures the response latency for
        observability and SLO monitoring.
        """
        self.success = True
        self.provider_message_id = provider_message_id
        self.response_time_ms = response_time_ms

    def mark_failure(self, error_message: str, response_time_ms: Optional[int] = None) -> None:
        """Record a failed delivery attempt.

        This method records the failure with an error message from the
        provider. The error message is preserved for debugging and for
        the dead letter queue processing logic.
        """
        self.success = False
        self.error_message = error_message
        self.response_time_ms = response_time_ms


@dataclass(frozen=True)
class DeliveryReceipt:
    """Immutable receipt confirming notification delivery outcome.

    The delivery receipt is the final record of a notification's delivery
    result. It aggregates information from the delivery attempt and any
    tracking events received from the provider. The receipt is emitted as
    a CloudEvent for downstream consumers such as the Analytics service.
    """

    notification_id: str
    channel: str
    status: DeliveryStatus
    provider: str = ""
    provider_message_id: Optional[str] = None
    delivered_at: Optional[datetime] = None
    error_reason: Optional[str] = None
    metadata: dict[str, str] = field(default_factory=dict)
