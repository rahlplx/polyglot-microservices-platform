"""
Preference management service for notification delivery control.

This module implements the preference management logic that governs how
recipients control their notification experience. The service loads
preferences from the repository, applies default values when no
preferences are configured, and provides convenience methods for checking
delivery eligibility.

The service acts as a facade over the preference repository, adding
business logic such as default preference construction and quiet hours
evaluation. This keeps the preference checking logic centralized and
ensures consistent behavior across all notification delivery paths.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..models.notification import NotificationChannel
from ..models.preference import (
    ChannelOptIn,
    ChannelPreference,
    NotificationPreference,
    QuietHours,
)
from ..ports.outbound.preference_store import PreferenceRepositoryPort
from ..services.notification_service import PreferencesNotConfiguredError

logger = logging.getLogger(__name__)


class PreferenceService:
    """Service for managing notification preferences.

    The PreferenceService loads and constructs notification preferences for
    recipients. When no preferences are explicitly configured, it provides
    sensible defaults (all channels enabled, no quiet hours). The service
    also provides convenience methods for checking delivery eligibility
    that combine preference checks with quiet hours evaluation.

    This service is used by the NotificationService as part of the delivery
    pipeline and by the preference management API for reading and updating
    preferences.
    """

    def __init__(self, preference_repo: PreferenceRepositoryPort) -> None:
        """Initialize the preference service.

        Args:
            preference_repo: Port for loading and storing preferences.
        """
        self._preference_repo = preference_repo

    async def get_preference(
        self, recipient_id: str
    ) -> NotificationPreference:
        """Load notification preferences for a recipient.

        If no preferences have been configured for the recipient, default
        preferences are returned with all channels enabled and no quiet
        hours. This permissive default ensures that new recipients receive
        notifications without requiring explicit preference configuration.

        Args:
            recipient_id: The recipient's unique identifier.

        Returns:
            The recipient's NotificationPreference, or default preferences
            if none are configured.
        """
        preference = await self._preference_repo.find_by_recipient_id(
            recipient_id
        )

        if preference is not None:
            return preference

        # Return default preferences (all channels enabled)
        return self._create_default_preferences(recipient_id)

    async def update_preference(
        self, preference: NotificationPreference
    ) -> NotificationPreference:
        """Save updated notification preferences for a recipient.

        Persists the preference changes and returns the saved preference
        entity. The save operation is idempotent.

        Args:
            preference: The updated preference entity to save.

        Returns:
            The persisted NotificationPreference.
        """
        return await self._preference_repo.save(preference)

    async def is_delivery_allowed(
        self,
        recipient_id: str,
        channel: NotificationChannel,
        is_urgent: bool = False,
    ) -> bool:
        """Check whether notification delivery is allowed for a recipient.

        Combines the preference check with quiet hours evaluation. Urgent
        notifications bypass quiet hours but still respect channel opt-out
        settings. Non-urgent notifications are suppressed during quiet
        hours and when the recipient has opted out of the channel.

        Args:
            recipient_id: The recipient's unique identifier.
            channel: The target notification channel.
            is_urgent: Whether the notification is urgent, which bypasses
                quiet hours but not channel opt-out.

        Returns:
            True if delivery is allowed, False otherwise.
        """
        preference = await self.get_preference(recipient_id)

        # Channel opt-out always blocks delivery
        if not preference.is_channel_enabled(channel.value):
            return False

        # Quiet hours block non-urgent delivery
        if not is_urgent:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            if preference.is_in_quiet_hours(now.hour, now.minute):
                return False

        return True

    async def get_recipients_in_quiet_hours(self) -> list[str]:
        """Find all recipient IDs currently in their quiet hours window.

        This method is used by the delivery optimizer to identify
        recipients whose notifications should be deferred. It delegates
        to the preference repository for efficient batch queries.

        Returns:
            A list of recipient IDs currently in quiet hours.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return await self._preference_repo.find_recipients_in_quiet_hours(
            now.hour, now.minute
        )

    @staticmethod
    def _create_default_preferences(recipient_id: str) -> NotificationPreference:
        """Create default notification preferences for a new recipient.

        Default preferences enable all channels with no frequency limits
        and no quiet hours. This permissive default ensures that new
        recipients receive notifications without requiring explicit setup.

        Args:
            recipient_id: The recipient's unique identifier.

        Returns:
            A NotificationPreference with default settings.
        """
        default_channel_prefs = [
            ChannelPreference(
                channel=ch.value,
                enabled=True,
                opt_in_status=ChannelOptIn.OPTED_IN,
                max_daily_frequency=None,
            )
            for ch in NotificationChannel
        ]

        return NotificationPreference(
            recipient_id=recipient_id,
            channel_preferences=default_channel_prefs,
            quiet_hours=None,
            timezone="UTC",
            global_opt_out=False,
        )
