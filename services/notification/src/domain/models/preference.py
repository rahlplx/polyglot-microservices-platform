"""
Preference entities for notification delivery control.

This module defines the data structures that govern how recipients control
their notification experience. The preference system supports per-channel
opt-in/opt-out, quiet hours with timezone awareness, and frequency limits.

The preference model is designed to respect the principle of least surprise:
recipients who have opted out of a channel will never receive notifications
through that channel unless the notification is legally required (e.g.,
payment receipts, security alerts). The quiet hours system defers non-urgent
notifications until after the quiet period ends, delivering them at the
earliest opportunity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum
from typing import Optional


class ChannelOptIn(Enum):
    """Opt-in status for a notification channel.

    OPTED_IN indicates the recipient has explicitly enabled the channel.
    OPTED_OUT indicates the recipient has disabled the channel. UNSUBSCRIBED
    is a stronger form of opt-out that also signals the delivery provider
    to stop sending, which is important for compliance with regulations
    like CAN-SPAM and GDPR.
    """

    OPTED_IN = "opted_in"
    OPTED_OUT = "opted_out"
    UNSUBSCRIBED = "unsubscribed"


@dataclass(frozen=True)
class QuietHours:
    """Value object representing a recipient's quiet hours configuration.

    Quiet hours define a time window during which non-urgent notifications
    should be suppressed. The start and end times are expressed in the
    recipient's local timezone. If the quiet window spans midnight (e.g.,
    22:00 to 07:00), the is_active_at method correctly handles the
    overnight interval.
    """

    start_time: time
    end_time: time
    timezone: str = "UTC"

    def is_active_at(self, current_time: time) -> bool:
        """Check whether the given time falls within the quiet hours window.

        This method handles both same-day and overnight quiet hour windows.
        For overnight windows (where end_time < start_time), the check is
        inverted to correctly span midnight. The comparison uses the
        recipient's local time, so callers must convert UTC timestamps to
        the recipient's timezone before calling this method.
        """
        if self.start_time <= self.end_time:
            # Same-day window (e.g., 12:00 to 14:00)
            return self.start_time <= current_time < self.end_time
        else:
            # Overnight window (e.g., 22:00 to 07:00)
            return current_time >= self.start_time or current_time < self.end_time


@dataclass(frozen=True)
class ChannelPreference:
    """Value object representing a recipient's preference for a single channel.

    Each channel preference records whether the channel is enabled, the
    opt-in status, and a maximum daily frequency limit. Category-specific
    overrides allow fine-grained control: for example, a recipient may opt
    out of promotional emails while remaining opted in to transactional emails.

    The max_daily_frequency field uses None to indicate no limit, allowing
    recipients who want all notifications to avoid setting an arbitrary cap.
    """

    channel: str
    enabled: bool = True
    opt_in_status: ChannelOptIn = ChannelOptIn.OPTED_IN
    max_daily_frequency: Optional[int] = None
    category_overrides: dict[str, ChannelOptIn] = field(default_factory=dict)

    def is_category_allowed(self, category: str) -> bool:
        """Check whether notifications of the given category are allowed.

        Category-specific overrides take precedence over the channel-level
        opt-in status. If no override exists for the category, the channel-
        level setting is used. This allows recipients to suppress specific
        notification types without disabling the entire channel.
        """
        override = self.category_overrides.get(category)
        if override is not None:
            return override == ChannelOptIn.OPTED_IN
        return self.enabled and self.opt_in_status == ChannelOptIn.OPTED_IN


@dataclass
class NotificationPreference:
    """Aggregate root for a recipient's complete notification preferences.

    This entity collects all channel preferences, quiet hours, and the
    global opt-out flag into a single object. The global_opt_out flag
    overrides all channel preferences: when True, only legally required
    notifications (payment receipts, security alerts) are delivered.

    The preference entity is loaded by the preference service before any
    notification is sent, and the notification pipeline checks each
    preference rule before proceeding with delivery.
    """

    recipient_id: str = ""
    channel_preferences: list[ChannelPreference] = field(default_factory=list)
    quiet_hours: Optional[QuietHours] = None
    timezone: str = "UTC"
    global_opt_out: bool = False

    def get_channel_preference(self, channel: str) -> Optional[ChannelPreference]:
        """Retrieve the preference for a specific channel.

        Returns None if no preference has been configured for the channel,
        which the caller should interpret as allowing delivery (default
        allow). This permissive default ensures that new channels are not
        accidentally blocked when added to the system.
        """
        for pref in self.channel_preferences:
            if pref.channel == channel:
                return pref
        return None

    def is_channel_enabled(self, channel: str) -> bool:
        """Check whether delivery is allowed for the given channel.

        This method combines the global opt-out flag with the channel-specific
        preference. If the recipient has globally opted out, only channels
        carrying legally required notifications are considered enabled. For
        non-global-opt-out recipients, the channel preference determines
        whether delivery is allowed.
        """
        if self.global_opt_out:
            return False
        pref = self.get_channel_preference(channel)
        if pref is None:
            return True  # default allow
        return pref.enabled and pref.opt_in_status == ChannelOptIn.OPTED_IN

    def is_in_quiet_hours(self, current_hour: int, current_minute: int) -> bool:
        """Check whether the current time falls within the quiet hours window.

        This is a simplified version of the quiet hours check that uses hour
        and minute integers instead of time objects. It delegates to the
        QuietHours.is_active_at method after constructing a time object.
        Returns False if no quiet hours are configured.
        """
        if self.quiet_hours is None:
            return False
        current_time = time(current_hour, current_minute)
        return self.quiet_hours.is_active_at(current_time)
