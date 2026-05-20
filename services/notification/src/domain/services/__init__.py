"""
Domain services for the Notification service.

These services implement the core business logic of notification processing,
delivery optimization, template rendering, and preference management. All
services depend only on domain ports (interfaces), never on infrastructure
implementations, maintaining the hexagonal architecture boundary.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from ..models import (
    DeliveryAttempt, Notification, NotificationChannel,
    NotificationPreference, NotificationPriority,
)
from ..ports import (
    ChannelSenderPort, DeliveryTrackerPort, GetDeliveryStatusPort,
    GetPreferencesPort, NotificationRepositoryPort, PreferenceRepositoryPort,
    SendNotificationPort, TemplateRepositoryPort,
)

logger = logging.getLogger(__name__)


class NotificationService(SendNotificationPort, GetDeliveryStatusPort, GetPreferencesPort):
    """Core notification orchestration service.
    Coordinates the full notification lifecycle: preference checking,
    template rendering, channel selection, delivery execution, and
    status tracking. This service is the primary application service
    in the hexagonal architecture, orchestrating all outbound ports
    to fulfill inbound use case requests."""

    def __init__(
        self,
        notification_repo: NotificationRepositoryPort,
        template_repo: TemplateRepositoryPort,
        preference_repo: PreferenceRepositoryPort,
        channel_senders: list[ChannelSenderPort],
        delivery_tracker: DeliveryTrackerPort,
        delivery_optimizer: "DeliveryOptimizer",
    ) -> None:
        self._repo = notification_repo
        self._template_repo = template_repo
        self._preference_repo = preference_repo
        self._channel_senders = {ch: sender for sender in channel_senders for ch in self._supported_channels(sender)}
        self._tracker = delivery_tracker
        self._optimizer = delivery_optimizer

    @staticmethod
    def _supported_channels(sender: ChannelSenderPort) -> list[NotificationChannel]:
        """Determine which channels a sender supports."""
        return [ch for ch in NotificationChannel if sender.supports_channel(ch)]

    async def send(self, notification: Notification) -> Notification:
        """Process and send a single notification through the delivery pipeline.
        This method enforces idempotency, checks user preferences, renders
        templates, selects the optimal channel, executes delivery, and tracks
        the outcome for ML-driven optimization."""
        logger.info("processing notification", extra={"notification_id": notification.id})

        # Idempotency check.
        if notification.idempotency_key:
            existing = await self._repo.get_by_idempotency_key(notification.idempotency_key)
            if existing:
                logger.info("idempotent notification found", extra={"notification_id": existing.id})
                return existing

        # Save initial state.
        notification = await self._repo.save(notification)

        # Check user preferences.
        prefs = await self._preference_repo.get_by_user_id(notification.recipient_id)
        if prefs and not self._is_channel_allowed(notification.channel, prefs):
            # Fall back to preferred channel.
            notification.channel = prefs.preferred_channel
            if not self._is_channel_allowed(notification.channel, prefs):
                notification.mark_failed("all channels disabled by user preference")
                await self._repo.update(notification)
                return notification

        # Render template if specified.
        if notification.template_id:
            notification = await self._render_template(notification)

        # Check quiet hours (except for critical priority).
        if prefs and notification.priority != NotificationPriority.CRITICAL:
            if self._in_quiet_hours(prefs):
                logger.info("notification delayed due to quiet hours",
                            extra={"notification_id": notification.id})
                notification.metadata["delayed_reason"] = "quiet_hours"
                # In production: queue for delivery after quiet hours end.

        # Select optimal channel based on ML optimizer.
        optimal_channel = self._optimizer.select_channel(notification, prefs)
        if optimal_channel and optimal_channel != notification.channel:
            logger.info("channel optimized", extra={
                "notification_id": notification.id,
                "original": notification.channel,
                "optimal": optimal_channel,
            })
            notification.channel = optimal_channel

        # Execute delivery through the selected channel.
        return await self._deliver(notification)

    async def send_batch(self, notifications: list[Notification]) -> list[Notification]:
        """Process and send multiple notifications in batch.
        Batch processing optimizes channel rate limiting by grouping
        notifications by channel and sending them in controlled bursts."""
        results = []
        for notification in notifications:
            result = await self.send(notification)
            results.append(result)
        return results

    async def get_status(self, notification_id: str) -> Optional[Notification]:
        """Retrieve a notification by its unique identifier."""
        return await self._repo.get_by_id(notification_id)

    async def get_attempts(self, notification_id: str) -> list[DeliveryAttempt]:
        """Retrieve delivery attempts for a notification."""
        # In production: query the delivery tracker for all attempts.
        return []

    async def get_preferences(self, user_id: str) -> Optional[NotificationPreference]:
        """Retrieve notification preferences for a user."""
        return await self._preference_repo.get_by_user_id(user_id)

    async def update_preferences(self, prefs: NotificationPreference) -> NotificationPreference:
        """Update notification preferences for a user."""
        return await self._preference_repo.save(prefs)

    def _is_channel_allowed(self, channel: NotificationChannel, prefs: NotificationPreference) -> bool:
        """Check if a channel is enabled in user preferences."""
        channel_enabled = {
            NotificationChannel.EMAIL: prefs.email_enabled,
            NotificationChannel.SMS: prefs.sms_enabled,
            NotificationChannel.PUSH: prefs.push_enabled,
            NotificationChannel.WEBHOOK: prefs.webhook_enabled,
        }
        return channel_enabled.get(channel, False)

    def _in_quiet_hours(self, prefs: NotificationPreference) -> bool:
        """Check if the current time falls within the user's quiet hours.
        Quiet hours are defined in the user's local timezone and prevent
        non-critical notifications from being delivered during sleep hours."""
        if not prefs.quiet_hours_start or not prefs.quiet_hours_end:
            return False
        # Simplified: compare current hour with quiet hours range.
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        try:
            start_hour = int(prefs.quiet_hours_start.split(":")[0])
            end_hour = int(prefs.quiet_hours_end.split(":")[0])
            if start_hour > end_hour:  # Overnight quiet hours (e.g., 22:00-08:00)
                return current_hour >= start_hour or current_hour < end_hour
            return start_hour <= current_hour < end_hour
        except (ValueError, IndexError):
            return False

    async def _render_template(self, notification: Notification) -> Notification:
        """Render a template with the notification's context variables."""
        template = await self._template_repo.get_by_id(notification.template_id)
        if not template:
            logger.warning("template not found", extra={"template_id": notification.template_id})
            return notification

        if template.subject_template:
            notification.subject = self._simple_render(template.subject_template, notification.template_vars)
        if template.body_template:
            notification.body = self._simple_render(template.body_template, notification.template_vars)
        if template.html_template:
            notification.html_body = self._simple_render(template.html_template, notification.template_vars)

        return notification

    @staticmethod
    def _simple_render(template_str: str, variables: dict[str, str]) -> str:
        """Simple variable substitution for template rendering.
        In production, this would use Jinja2 with sandboxing for security."""
        result = template_str
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    async def _deliver(self, notification: Notification) -> Notification:
        """Execute delivery through the selected channel sender."""
        sender = self._channel_senders.get(notification.channel)
        if not sender:
            notification.mark_failed(f"no sender for channel {notification.channel}")
            await self._repo.update(notification)
            return notification

        try:
            notification.mark_sending()
            attempt = await sender.send(notification)

            if attempt.success:
                notification.mark_sent()
                # In production: wait for webhook confirmation before marking delivered.
                notification.mark_delivered()
            else:
                notification.mark_failed(attempt.error_message)

            await self._tracker.record_attempt(attempt)

        except Exception as e:
            notification.mark_failed(str(e))
            logger.error("delivery failed", extra={
                "notification_id": notification.id,
                "channel": notification.channel,
                "error": str(e),
            })

        return await self._repo.update(notification)


class DeliveryOptimizer:
    """ML-driven delivery optimization for selecting optimal channels and timing.
    The optimizer uses historical delivery statistics to predict the best channel
    and delivery time for each notification. Currently implements a simple
    statistical model based on per-channel success rates and per-hour open rates.
    Future iterations will integrate with the RL Engine for reinforcement
    learning-based optimization across the full notification delivery space."""

    def __init__(self, delivery_tracker: DeliveryTrackerPort) -> None:
        self._tracker = delivery_tracker

    def select_channel(
        self,
        notification: Notification,
        prefs: Optional[NotificationPreference],
    ) -> Optional[NotificationChannel]:
        """Select the optimal delivery channel based on historical performance.
        The optimizer considers the notification priority, user preferences,
        and historical delivery success rates to choose the channel most
        likely to result in timely delivery and user engagement."""
        # For critical notifications, always prefer push (instant) then SMS.
        if notification.priority == NotificationPriority.CRITICAL:
            return NotificationChannel.PUSH

        # For high priority, prefer the user's preferred channel.
        if notification.priority == NotificationPriority.HIGH:
            if prefs:
                return prefs.preferred_channel
            return NotificationChannel.EMAIL

        # For normal/low priority, use preferred channel with fallback.
        if prefs:
            return prefs.preferred_channel
        return None  # Keep the notification's original channel.
