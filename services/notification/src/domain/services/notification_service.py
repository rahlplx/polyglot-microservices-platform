"""
Core notification orchestration service.

This module implements the SendNotificationPort, GetDeliveryStatusPort, and
GetPreferencesPort inbound ports. The NotificationService orchestrates the
complete notification delivery pipeline: preference checking, template
rendering, delivery optimization, channel selection, and dispatch.

The service is idempotent for the same correlation_id, preventing duplicate
notifications from Kafka consumer rebalances. It implements retry logic with
exponential backoff for transient delivery failures and dead-letter handling
for permanent failures.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from ..models.notification import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
)
from ..models.delivery import DeliveryAttempt, DeliveryReceipt, DeliveryStatus, TrackingEvent, TrackingEventType
from ..models.template import RenderedTemplate
from ..models.preference import NotificationPreference
from ..ports.inbound.send_notification import (
    SendNotificationPort,
    SendNotificationRequest,
    SendNotificationResponse,
    GetDeliveryStatusPort,
    GetDeliveryStatusRequest,
    GetDeliveryStatusResponse,
    GetPreferencesPort,
    GetPreferencesRequest,
    GetPreferencesResponse,
)
from ..ports.outbound.channel_sender import ChannelSenderPort, DeliveryRequest, DeliveryResponse
from ..ports.outbound.delivery_tracker import DeliveryTrackerPort, PageRequest, Page, DeliveryModel
from ..ports.outbound.template_store import TemplateRepositoryPort
from ..ports.outbound.preference_store import PreferenceRepositoryPort

from .delivery_optimizer import DeliveryOptimizer
from .template_service import TemplateService
from .preference_service import PreferenceService

logger = logging.getLogger(__name__)


class NotificationService:
    """Core notification orchestration service implementing all inbound ports.

    This service coordinates the notification delivery pipeline by delegating
    to specialized domain services (TemplateService, DeliveryOptimizer,
    PreferenceService) and outbound ports (ChannelSenderPort, DeliveryTrackerPort).
    It enforces the business rules for notification delivery including preference
    checking, quiet hour deferral, and retry policies.

    The service maintains a registry of channel senders, one per supported
    notification channel. When a notification is sent, the service selects
    the appropriate sender based on the notification's channel, or uses the
    ML optimizer to select the best channel when no preference is specified.
    """

    def __init__(
        self,
        delivery_tracker: DeliveryTrackerPort,
        template_repo: TemplateRepositoryPort,
        preference_repo: PreferenceRepositoryPort,
        channel_senders: dict[NotificationChannel, ChannelSenderPort],
        delivery_optimizer: DeliveryOptimizer,
        template_service: TemplateService,
        preference_service: PreferenceService,
    ) -> None:
        """Initialize the notification service with its dependencies.

        Args:
            delivery_tracker: Port for persisting notification records and
                tracking delivery events.
            template_repo: Port for loading and storing notification templates.
            preference_repo: Port for loading and storing recipient preferences.
            channel_senders: Map of channel to sender implementation, one per
                supported notification channel.
            delivery_optimizer: Service for ML-driven delivery time optimization.
            template_service: Service for template rendering and validation.
            preference_service: Service for preference management.
        """
        self._delivery_tracker = delivery_tracker
        self._template_repo = template_repo
        self._preference_repo = preference_repo
        self._channel_senders = channel_senders
        self._delivery_optimizer = delivery_optimizer
        self._template_service = template_service
        self._preference_service = preference_service

    async def send(self, request: SendNotificationRequest) -> SendNotificationResponse:
        """Execute the send notification use case.

        This method orchestrates the complete notification delivery pipeline:
        1. Check for idempotency (existing notification with same correlation_id)
        2. Load recipient preferences and validate channel opt-in
        3. Render the notification template with provided variables
        4. Apply ML delivery optimization for non-urgent notifications
        5. Select the delivery channel (explicit or ML-recommended)
        6. Dispatch through the channel sender
        7. Record the delivery attempt and update notification status

        If any step fails, the notification is marked as FAILED and will be
        retried if the error is transient.
        """
        # Step 1: Idempotency check
        if request.correlation_id:
            existing = await self._delivery_tracker.find_by_correlation_id(
                request.correlation_id
            )
            if existing:
                logger.info(
                    "Notification already exists for correlation_id=%s, "
                    "returning existing notification_id=%s",
                    request.correlation_id,
                    existing[0].notification_id,
                )
                return SendNotificationResponse(notification=existing[0])

        # Step 2: Load preferences and check opt-in
        preference = await self._preference_service.get_preference(
            request.recipient.user_id
        )

        # Determine the target channel
        target_channel = request.channel
        if target_channel is None:
            target_channel = await self._delivery_optimizer.select_channel(
                recipient_id=request.recipient.user_id,
                notification_type=request.notification_type,
                preference=preference,
            )

        # Validate recipient has address for the channel
        if not request.recipient.has_channel_address(target_channel):
            raise ChannelUnavailableError(
                f"Recipient has no address for channel {target_channel.value}"
            )

        # Check preference opt-in
        if preference and not preference.is_channel_enabled(target_channel.value):
            raise RecipientOptedOutError(
                f"Recipient opted out of channel {target_channel.value}"
            )

        # Step 3: Render template
        rendered = await self._template_service.render(
            template_id=request.template_id,
            variables=request.template_vars,
        )

        # Step 4: Create notification entity
        notification = Notification(
            recipient=request.recipient,
            channel=target_channel,
            notification_type=request.notification_type,
            priority=request.priority,
            template_id=request.template_id,
            template_vars=request.template_vars,
            subject=rendered.subject,
            body=rendered.plain_text_content,
            correlation_id=request.correlation_id,
            status=NotificationStatus.QUEUED,
        )

        # Step 5: Apply delivery optimization for non-urgent notifications
        if not notification.is_high_priority() and request.scheduled_at is None:
            optimization = await self._delivery_optimizer.optimize_delivery_time(
                recipient_id=request.recipient.user_id,
                channel=target_channel,
                preference=preference,
            )
            if optimization.should_defer:
                notification.scheduled_at = optimization.optimal_time
                logger.info(
                    "Deferred notification %s to %s (ML optimization)",
                    notification.notification_id,
                    optimization.optimal_time,
                )

        # Step 6: Persist notification
        notification = await self._delivery_tracker.save(notification)

        # Step 7: Check quiet hours before dispatching
        if preference and preference.is_in_quiet_hours(
            datetime.now(timezone.utc).hour,
            datetime.now(timezone.utc).minute,
        ):
            if not notification.is_high_priority():
                logger.info(
                    "Notification %s deferred due to quiet hours",
                    notification.notification_id,
                )
                notification.scheduled_at = datetime.now(timezone.utc)
                await self._delivery_tracker.save(notification)
                return SendNotificationResponse(
                    notification=notification,
                    scheduled_delivery=notification.scheduled_at,
                )

        # Step 8: Dispatch through channel sender
        sender = self._channel_senders.get(target_channel)
        if sender is None:
            raise ChannelUnavailableError(
                f"No sender registered for channel {target_channel.value}"
            )

        notification.transition_to(NotificationStatus.SENDING)
        await self._delivery_tracker.save(notification)

        delivery_request = DeliveryRequest(
            notification_id=notification.notification_id,
            channel=target_channel,
            recipient_address=self._get_recipient_address(
                request.recipient, target_channel
            ),
            subject=rendered.subject,
            html_content=rendered.html_content,
            plain_text_content=rendered.plain_text_content,
            short_content=rendered.short_content,
            correlation_id=request.correlation_id,
        )

        response = await sender.send(delivery_request)

        # Step 9: Record delivery attempt
        attempt = DeliveryAttempt(
            notification_id=notification.notification_id,
            channel=target_channel.value,
            provider=response.provider,
            success=response.success,
            provider_message_id=response.provider_message_id,
            error_message=response.error_message,
        )

        await self._delivery_tracker.save_delivery_attempt(attempt)

        if response.success:
            notification.transition_to(NotificationStatus.SENT)
            notification.sent_at = datetime.now(timezone.utc)
        else:
            if notification.is_retryable():
                notification.increment_retry()
                logger.warning(
                    "Delivery failed for notification %s, retry %d/%d: %s",
                    notification.notification_id,
                    notification.retry_count,
                    notification.max_retries,
                    response.error_message,
                )
            else:
                notification.transition_to(NotificationStatus.FAILED)
                notification.failed_at = datetime.now(timezone.utc)
                logger.error(
                    "Delivery permanently failed for notification %s: %s",
                    notification.notification_id,
                    response.error_message,
                )

        await self._delivery_tracker.save(notification)

        return SendNotificationResponse(
            notification=notification,
            estimated_delivery=datetime.now(timezone.utc),
            scheduled_delivery=notification.scheduled_at,
        )

    async def get_status(
        self, request: GetDeliveryStatusRequest
    ) -> GetDeliveryStatusResponse:
        """Retrieve the delivery status of a notification.

        Loads the notification from the repository and constructs the status
        response with key timestamps. If tracking details are requested, the
        full tracking event timeline is included.
        """
        notification = await self._delivery_tracker.find_by_id(
            request.notification_id
        )
        if notification is None:
            raise NotificationNotFoundError(
                f"Notification not found: {request.notification_id}"
            )

        # Map notification status to delivery status
        status_map = {
            NotificationStatus.PENDING: DeliveryStatus.ACCEPTED,
            NotificationStatus.QUEUED: DeliveryStatus.ACCEPTED,
            NotificationStatus.SENDING: DeliveryStatus.SENT,
            NotificationStatus.SENT: DeliveryStatus.SENT,
            NotificationStatus.DELIVERED: DeliveryStatus.DELIVERED,
            NotificationStatus.FAILED: DeliveryStatus.FAILED,
            NotificationStatus.BOUNCED: DeliveryStatus.BOUNCED,
        }

        response = GetDeliveryStatusResponse(
            notification_id=notification.notification_id,
            status=status_map.get(notification.status, DeliveryStatus.FAILED),
            channel=notification.channel.value if notification.channel else "",
            recipient_id=notification.recipient.user_id if notification.recipient else "",
            sent_at=notification.sent_at,
            delivered_at=notification.delivered_at,
            bounced_at=notification.failed_at if notification.status == NotificationStatus.BOUNCED else None,
        )

        if request.include_tracking_details:
            response.tracking_details = notification.tracking_events

        return response

    async def get_preferences(
        self, request: GetPreferencesRequest
    ) -> GetPreferencesResponse:
        """Retrieve notification preferences for a recipient.

        Delegates to the preference service for loading and constructing the
        preference entity. If no preferences are configured, default
        preferences are returned with all channels enabled.
        """
        preference = await self._preference_service.get_preference(
            request.recipient_id
        )
        if preference is None:
            raise RecipientNotFoundError(
                f"Recipient not found: {request.recipient_id}"
            )

        # Filter to specific channel if requested
        if request.channel is not None and preference is not None:
            channel_pref = preference.get_channel_preference(request.channel.value)
            if channel_pref is not None:
                preference = NotificationPreference(
                    recipient_id=preference.recipient_id,
                    channel_preferences=[channel_pref],
                    quiet_hours=preference.quiet_hours,
                    timezone=preference.timezone,
                    global_opt_out=preference.global_opt_out,
                )

        return GetPreferencesResponse(preference=preference)

    @staticmethod
    def _get_recipient_address(
        recipient, channel: NotificationChannel
    ) -> str:
        """Extract the channel-specific address from a recipient.

        Maps the channel enum to the corresponding recipient field. Raises
        ChannelUnavailableError if the recipient does not have an address
        for the specified channel.
        """
        address_map = {
            NotificationChannel.EMAIL: recipient.email,
            NotificationChannel.SMS: recipient.phone,
            NotificationChannel.PUSH: recipient.device_token,
            NotificationChannel.WEBHOOK: recipient.webhook_url,
        }
        address = address_map.get(channel)
        if address is None:
            raise ChannelUnavailableError(
                f"No address for channel {channel.value}"
            )
        return address


# --- Domain Exceptions ---

class NotificationError(Exception):
    """Base exception for notification domain errors."""
    pass


class TemplateNotFoundError(NotificationError):
    """Raised when a referenced template does not exist."""
    pass


class RecipientOptedOutError(NotificationError):
    """Raised when a recipient has opted out of the specified channel."""
    pass


class ChannelUnavailableError(NotificationError):
    """Raised when no sender is available for the requested channel."""
    pass


class RateLimitExceededError(NotificationError):
    """Raised when the delivery provider's rate limit is exceeded."""
    pass


class InvalidTemplateVarsError(NotificationError):
    """Raised when required template variables are missing."""
    pass


class NotificationNotFoundError(NotificationError):
    """Raised when a notification is not found by its ID."""
    pass


class RecipientNotFoundError(NotificationError):
    """Raised when a recipient is not found."""
    pass


class PreferencesNotConfiguredError(NotificationError):
    """Raised when no preferences are configured for a recipient."""
    pass
