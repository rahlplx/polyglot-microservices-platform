"""
Domain exceptions for the Notification service.

Centralized exception definitions to avoid circular imports between
domain service modules. Each exception is a domain-level concept
that may be raised by multiple services.
"""

from __future__ import annotations


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
