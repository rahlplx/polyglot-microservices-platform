"""
Preference repository port for recipient preference persistence.

This module defines the outbound port that the preference service uses to
load and store notification preferences. Preferences are stored per recipient
and include per-channel opt-in/opt-out settings, quiet hours configuration,
and the global opt-out flag.

The preference store is queried before every notification delivery to ensure
that recipient opt-out choices are respected. Implementations must provide
low-latency reads to meet the p99 < 200ms SLO for the delivery pipeline.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from ...models.preference import NotificationPreference


@runtime_checkable
class PreferenceRepositoryPort(Protocol):
    """Outbound port for notification preference persistence.

    This port provides operations for loading and saving recipient
    notification preferences. The preference service uses this port to
    implement the GetPreferencesPort inbound port and to update preferences
    through the preference management API.
    """

    async def find_by_recipient_id(self, recipient_id: str) -> Optional[NotificationPreference]:
        """Retrieve preferences for a specific recipient.

        Returns the recipient's complete notification preference set, or
        None if no preferences have been configured. When None is returned,
        the caller should apply default preferences (all channels enabled,
        no quiet hours).
        """
        ...

    async def save(self, preference: NotificationPreference) -> NotificationPreference:
        """Persist notification preferences for a recipient.

        Creates or updates the recipient's preference set. The save
        operation is idempotent: saving the same preference twice has the
        same effect as saving it once.
        """
        ...

    async def find_recipients_in_quiet_hours(self, hour: int, minute: int) -> list[str]:
        """Find all recipient IDs currently in their quiet hours window.

        This method is used by the delivery optimizer to identify recipients
        whose notifications should be deferred. It returns a list of
        recipient IDs whose quiet hours configuration includes the given
        time in their local timezone.
        """
        ...
