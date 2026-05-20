"""
Channel sender port for multi-channel notification delivery.

This module defines the outbound port that abstracts the interface to external
notification delivery providers. Each channel (email, SMS, push, webhook) has
its own adapter implementation that translates the rendered notification
content into the provider's API format.

The port uses a request/response pattern with explicit error reporting,
allowing the domain service to implement retry logic and fallback strategies
without knowledge of provider-specific error semantics. The delivery request
includes the fully rendered content so the channel adapter does not need
to interact with the template engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from ...models.notification import NotificationChannel


@dataclass(frozen=True)
class DeliveryRequest:
    """Request to send a notification through a delivery channel.

    The delivery request contains the fully rendered notification content
    (subject, HTML body, plain text body, short body) along with the
    recipient's channel-specific address. The channel adapter selects the
    appropriate content variant based on the channel type and provider
    requirements.
    """

    notification_id: str
    channel: NotificationChannel
    recipient_address: str
    subject: Optional[str] = None
    html_content: Optional[str] = None
    plain_text_content: Optional[str] = None
    short_content: Optional[str] = None
    metadata: dict[str, str] = field(default_factory=dict)
    correlation_id: str = ""


@dataclass
class DeliveryResponse:
    """Response from a channel delivery attempt.

    The response indicates whether the delivery was accepted by the provider,
    the provider's message identifier for tracking, and any error information.
    A successful response (success=True) does not guarantee delivery to the
    recipient; it only confirms that the provider accepted the message for
    processing. Final delivery confirmation comes asynchronously via webhook
    callbacks.
    """

    success: bool
    provider: str = ""
    provider_message_id: Optional[str] = None
    error_message: Optional[str] = None
    response_time_ms: Optional[int] = None
    retry_after_seconds: Optional[int] = None
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class ChannelSenderPort(Protocol):
    """Outbound port for sending notifications through a delivery channel.

    Each channel (email, SMS, push, webhook) implements this interface.
    The port abstracts away provider-specific API details, allowing the
    domain service to treat all channels uniformly. Implementations should
    handle transient failures by returning a response with retry_after_seconds
    set, allowing the caller to implement backoff logic.

    Implementations behind an ACL sidecar should route all external calls
    through the sidecar to enforce circuit breaking and rate limiting.
    """

    @property
    def channel(self) -> NotificationChannel:
        """The channel this sender handles."""
        ...

    async def send(self, request: DeliveryRequest) -> DeliveryResponse:
        """Send a notification through this channel.

        Args:
            request: The delivery request with rendered content and
                recipient address.

        Returns:
            The delivery response indicating success or failure with
            provider details.

        Raises:
            ChannelUnavailableError: If the delivery provider is unreachable.
            RateLimitExceededError: If the provider's rate limit is exceeded.
        """
        ...

    async def health_check(self) -> bool:
        """Check whether the channel sender is healthy and available.

        Returns True if the sender can accept delivery requests, False
        otherwise. This is used by the channel router to skip unavailable
        channels during delivery attempts.
        """
        ...
