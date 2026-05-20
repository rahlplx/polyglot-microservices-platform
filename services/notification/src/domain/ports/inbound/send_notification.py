"""
Inbound port interfaces for notification use cases.

This module defines the primary inbound ports that constitute the notification
service's API surface. These ports are implemented by the domain services and
invoked by inbound adapters (event consumers, REST controllers, gRPC handlers).

Each port follows the command/query separation principle: SendNotification is
a command that creates side effects, while GetDeliveryStatus and GetPreferences
are pure queries that return data without modifying state. This separation
simplifies reasoning about the system and enables independent optimization of
read and write paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from ...models.notification import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationType,
    Recipient,
)
from ...models.preference import NotificationPreference
from ...models.delivery import DeliveryStatus


# --- Request/Response types for SendNotification ---

@dataclass(frozen=True)
class SendNotificationRequest:
    """Input for the SendNotification use case.

    Contains all information needed to create and deliver a notification.
    The template_id references a stored template, and template_vars provides
    the context variables for rendering. The priority field controls whether
    the ML delivery optimizer is invoked. If scheduled_at is provided, the
    notification will be held until that time before delivery is attempted.
    """

    recipient: Recipient
    channel: Optional[NotificationChannel] = None
    template_id: str = ""
    template_vars: dict[str, str] = field(default_factory=dict)
    notification_type: Optional[NotificationType] = None
    priority: NotificationPriority = NotificationPriority.NORMAL
    scheduled_at: Optional[datetime] = None
    correlation_id: str = ""


@dataclass
class SendNotificationResponse:
    """Output of the SendNotification use case.

    Contains the created notification entity (with its assigned ID and
    initial status), the estimated delivery time, and the scheduled delivery
    time if the ML optimizer determined a better delivery window.
    """

    notification: Notification
    estimated_delivery: Optional[datetime] = None
    scheduled_delivery: Optional[datetime] = None


# --- Request/Response types for GetDeliveryStatus ---

@dataclass(frozen=True)
class GetDeliveryStatusRequest:
    """Input for the GetDeliveryStatus query.

    The include_tracking_details flag controls whether the full tracking
    event timeline is included in the response. When False, only the
    current status and key timestamps are returned, which is more efficient
    for status polling.
    """

    notification_id: str
    include_tracking_details: bool = False


@dataclass
class GetDeliveryStatusResponse:
    """Output of the GetDeliveryStatus query.

    Provides the current delivery status along with key timestamps. When
    tracking details are requested, the full timeline of tracking events
    from the delivery provider is included, giving a complete picture of
    the notification's delivery journey.
    """

    notification_id: str
    status: DeliveryStatus
    channel: str
    recipient_id: str
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    clicked_at: Optional[datetime] = None
    bounced_at: Optional[datetime] = None
    tracking_details: list = field(default_factory=list)


# --- Request/Response types for GetPreferences ---

@dataclass(frozen=True)
class GetPreferencesRequest:
    """Input for the GetPreferences query.

    Optionally filters preferences to a specific channel. When channel is
    None, all channel preferences are returned.
    """

    recipient_id: str
    channel: Optional[NotificationChannel] = None


@dataclass
class GetPreferencesResponse:
    """Output of the GetPreferences query.

    Contains the recipient's complete notification preferences, including
    per-channel settings, quiet hours, and the global opt-out flag.
    """

    preference: NotificationPreference


# --- Port Protocols ---

@runtime_checkable
class SendNotificationPort(Protocol):
    """Primary use case port for sending notifications.

    This port orchestrates the complete notification delivery pipeline:
    template rendering, preference checking, delivery optimization, and
    channel dispatch. It is the main entry point for all notification
    creation, whether triggered by domain events or direct API calls.

    Implementations must be idempotent for the same correlation_id to
    prevent duplicate notifications from Kafka consumer rebalances.
    """

    async def send(self, request: SendNotificationRequest) -> SendNotificationResponse:
        """Execute the send notification use case.

        Args:
            request: The notification request with recipient, template,
                and delivery parameters.

        Returns:
            The response containing the created notification and delivery
            estimates.

        Raises:
            TemplateNotFoundError: If the template_id does not exist.
            RecipientOptedOutError: If the recipient opted out of the channel.
            ChannelUnavailableError: If no sender is available for the channel.
            InvalidTemplateVarsError: If required template variables are missing.
        """
        ...


@runtime_checkable
class GetDeliveryStatusPort(Protocol):
    """Query port for retrieving notification delivery status.

    This port supports operational monitoring and customer support tools
    by providing real-time visibility into notification delivery progress.
    It aggregates tracking events from the delivery provider into a
    coherent timeline, deduplicating events that may be sent multiple times.
    """

    async def get_status(self, request: GetDeliveryStatusRequest) -> GetDeliveryStatusResponse:
        """Retrieve the delivery status of a notification.

        Args:
            request: The query request with notification ID and detail flag.

        Returns:
            The delivery status response with timestamps and optional
            tracking details.

        Raises:
            NotificationNotFoundError: If the notification_id does not exist.
        """
        ...


@runtime_checkable
class GetPreferencesPort(Protocol):
    """Query port for retrieving notification preferences.

    This port is called by the SendNotification pipeline before delivering
    any notification to verify that the recipient has not opted out of the
    specified channel. It can also be used by preference management UIs
    to display current settings.
    """

    async def get_preferences(self, request: GetPreferencesRequest) -> GetPreferencesResponse:
        """Retrieve notification preferences for a recipient.

        Args:
            request: The query request with recipient ID and optional channel
                filter.

        Returns:
            The recipient's notification preferences.

        Raises:
            RecipientNotFoundError: If the recipient_id does not exist.
            PreferencesNotConfiguredError: If no preferences are configured.
        """
        ...
