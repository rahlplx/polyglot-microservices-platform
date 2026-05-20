"""
Delivery tracker port for notification delivery tracking and persistence.

This module defines the outbound port that the notification service uses to
persist notification records and track delivery events. The delivery tracker
stores notification entities, appends tracking events, and provides query
capabilities for delivery status and analytics.

The port supports the append-only tracking event pattern: events are recorded
as they arrive and are never modified or deleted. This event sourcing approach
provides a complete audit trail and supports the ML model's training data
pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from ...models.notification import Notification
from ...models.delivery import DeliveryAttempt, TrackingEvent


@dataclass(frozen=True)
class PageRequest:
    """Pagination parameters for list queries.

    The page size is bounded to prevent unbounded result sets that could
    degrade database performance. The offset is zero-based.
    """

    page_size: int = 20
    offset: int = 0


@dataclass
class Page:
    """Paginated result set.

    Contains the items for the current page along with total count
    information for rendering pagination controls.
    """

    items: list = field(default_factory=list)
    total_count: int = 0
    page_size: int = 20
    offset: int = 0

    @property
    def has_more(self) -> bool:
        """Check whether there are more items beyond this page."""
        return (self.offset + len(self.items)) < self.total_count


@dataclass(frozen=True)
class DeliveryModel:
    """ML delivery optimization model parameters.

    Stores the learned parameters for the delivery time optimization model.
    The model uses statistical features (open rates by hour, channel, day
    of week) to predict the optimal delivery window. Parameters are stored
    as JSONB in PostgreSQL for flexibility and versioned for A/B testing.
    """

    model_version: str = "v1"
    parameters: dict[str, float] = field(default_factory=dict)
    trained_at: datetime = field(default_factory=datetime.now)
    accuracy: float = 0.0
    feature_importance: dict[str, float] = field(default_factory=dict)


@runtime_checkable
class DeliveryTrackerPort(Protocol):
    """Outbound port for notification persistence and delivery tracking.

    This port manages all persistent data for the notification service,
    including notification records, tracking events, delivery attempts,
    and ML model parameters. It supports both the operational delivery
    pipeline (save, find, append events) and the analytics/ML pipeline
    (find pending retries, save model parameters).
    """

    async def save(self, notification: Notification) -> Notification:
        """Persist a notification record with its current status.

        Creates or updates the notification in the data store. The
        notification ID is used as the primary key for deduplication.
        """
        ...

    async def find_by_id(self, notification_id: str) -> Optional[Notification]:
        """Retrieve a notification by its unique identifier.

        Returns None if no notification with the given ID exists.
        """
        ...

    async def find_by_correlation_id(self, correlation_id: str) -> list[Notification]:
        """Retrieve all notifications linked to a correlation ID.

        Returns notifications in creation order. Used for end-to-end
        traceability across service boundaries.
        """
        ...

    async def find_by_recipient(
        self, recipient_id: str, page: PageRequest
    ) -> Page:
        """Retrieve paginated notifications for a recipient.

        Returns notifications sorted by creation time in descending order
        (most recent first).
        """
        ...

    async def append_tracking_event(self, event: TrackingEvent) -> None:
        """Append a tracking event to a notification's event history.

        Events are deduplicated by event_id to handle provider webhook
        retransmissions. The notification's status is updated based on
        the event type.
        """
        ...

    async def save_delivery_attempt(self, attempt: DeliveryAttempt) -> None:
        """Persist a delivery attempt record.

        Delivery attempts are stored independently from notifications to
        support the retry mechanism and delivery analytics.
        """
        ...

    async def find_pending_retry(self, limit: int = 50) -> list[Notification]:
        """Retrieve notifications that are pending retry delivery.

        Returns notifications in FAILED status that have not exceeded
        their maximum retry count, sorted by creation time.
        """
        ...

    async def save_delivery_model(self, model: DeliveryModel) -> None:
        """Persist the ML delivery optimization model parameters.

        The model parameters are stored as JSONB with versioning to
        support A/B testing of different model configurations.
        """
        ...

    async def load_delivery_model(self, model_version: str = "latest") -> Optional[DeliveryModel]:
        """Load the ML delivery optimization model parameters.

        Returns the model parameters for the specified version, or the
        latest version if model_version is "latest".
        """
        ...
