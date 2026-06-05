"""
Webhook delivery channel adapter with retry logic.

This module implements the ChannelSenderPort for webhook notifications.
It sends HTTP POST requests to configured webhook endpoints with
exponential backoff retry for transient failures. Webhooks are used
for internal system integrations (e.g., inventory alerts to procurement
systems) and third-party service integrations.

The adapter includes configurable timeout, retry behavior, and request
signing for webhook authentication. Failed deliveries are retried up to
the configured maximum with exponential backoff between attempts.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
from typing import Any, Optional
from urllib.parse import urlparse

from ....domain.models.notification import NotificationChannel
from ....domain.ports.outbound.channel_sender import (
    DeliveryRequest,
    DeliveryResponse,
)

logger = logging.getLogger(__name__)


class WebhookSenderAdapter:
    """Webhook channel sender with retry logic and request signing.

    This adapter sends webhook notifications as HTTP POST requests to
    configured endpoints. It implements exponential backoff retry for
    transient failures (5xx responses and network errors) and request
    signing using HMAC-SHA256 for webhook authentication.

    The adapter supports custom headers, configurable timeouts, and
    payload transformation. Webhook delivery is fire-and-forget for
    non-critical notifications, but critical webhooks are retried up
    to the maximum attempt count before marking as permanently failed.
    """

    def __init__(
        self,
        default_timeout: int = 30,
        max_retries: int = 3,
        base_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 60.0,
        signing_secret: Optional[str] = None,
        acl_sidecar_url: Optional[str] = None,
    ) -> None:
        """Initialize the webhook sender adapter.

        Args:
            default_timeout: HTTP request timeout in seconds.
            max_retries: Maximum number of retry attempts for failed deliveries.
            base_backoff_seconds: Initial backoff interval for exponential retry.
            max_backoff_seconds: Maximum backoff interval cap.
            signing_secret: HMAC-SHA256 signing secret for webhook authentication.
            acl_sidecar_url: URL of the ACL sidecar for external communication.
        """
        self._default_timeout = default_timeout
        self._max_retries = max_retries
        self._base_backoff_seconds = base_backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._signing_secret = signing_secret
        self._acl_sidecar_url = acl_sidecar_url

    @property
    def channel(self) -> NotificationChannel:
        """The webhook notification channel."""
        return NotificationChannel.WEBHOOK

    async def send(self, request: DeliveryRequest) -> DeliveryResponse:
        """Send a webhook notification with retry logic.

        Sends an HTTP POST request to the webhook URL specified in the
        recipient address. The request body includes the notification
        content and metadata. Transient failures (5xx, network errors)
        are retried with exponential backoff.

        Args:
            request: The delivery request with webhook content.

        Returns:
            The delivery response indicating success or failure.
        """
        start_time = time.monotonic()

        url = request.recipient_address

        # SECURITY: Prevent SSRF by validating the webhook URL
        if not await self._is_safe_url(url):
            logger.error("Blocked unsafe webhook URL: %s", url)
            return DeliveryResponse(
                success=False,
                provider="webhook",
                error_message="SSRF Protection: Unsafe webhook URL blocked",
            )

        payload = self._build_payload(request)
        headers = self._build_headers(request, payload)

        last_error: Optional[str] = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._make_request(
                    url, payload, headers
                )
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                response.response_time_ms = elapsed_ms

                if response.success:
                    return response

                # Don't retry client errors (4xx)
                if "4" in (response.error_message or "")[:3]:
                    return response

                last_error = response.error_message

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Webhook attempt %d/%d failed for notification %s: %s",
                    attempt + 1,
                    self._max_retries + 1,
                    request.notification_id,
                    e,
                )

            # Exponential backoff before retry
            if attempt < self._max_retries:
                backoff = min(
                    self._base_backoff_seconds * (2 ** attempt),
                    self._max_backoff_seconds,
                )
                logger.debug("Retrying webhook in %.1f seconds", backoff)
                await asyncio.sleep(backoff)

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        return DeliveryResponse(
            success=False,
            provider="webhook",
            error_message=f"All {self._max_retries + 1} attempts failed: {last_error}",
            response_time_ms=elapsed_ms,
        )

    async def health_check(self) -> bool:
        """Check if the webhook sender is operational.

        The webhook sender is always considered healthy because it
        does not maintain persistent connections to external services.
        Each delivery creates a new HTTP request.
        """
        return True

    async def _make_request(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> DeliveryResponse:
        """Execute a single HTTP POST request to the webhook endpoint.

        Sends the payload as a JSON-encoded POST request with the
        specified headers. Returns a DeliveryResponse based on the
        HTTP status code.

        Args:
            url: The webhook endpoint URL.
            payload: The request payload dictionary.
            headers: The HTTP headers dictionary.

        Returns:
            The delivery response based on the HTTP result.
        """
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._default_timeout,
                )

            if 200 <= resp.status_code < 300:
                logger.info("Webhook delivered to %s: status=%d", url, resp.status_code)
                return DeliveryResponse(
                    success=True,
                    provider="webhook",
                    provider_message_id=payload.get("notification_id", ""),
                )
            else:
                return DeliveryResponse(
                    success=False,
                    provider="webhook",
                    error_message=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )

        except httpx.TimeoutException:
            return DeliveryResponse(
                success=False,
                provider="webhook",
                error_message="Request timed out",
                retry_after_seconds=5,
            )
        except httpx.ConnectError as e:
            return DeliveryResponse(
                success=False,
                provider="webhook",
                error_message=f"Connection failed: {e}",
                retry_after_seconds=10,
            )

    def _build_payload(self, request: DeliveryRequest) -> dict[str, Any]:
        """Build the webhook request payload.

        Constructs a standardized payload that includes the notification
        content, metadata, and delivery information. The payload format
        is consistent across all webhook deliveries for ease of
        integration by consuming systems.

        Args:
            request: The delivery request.

        Returns:
            The payload dictionary for the HTTP request body.
        """
        return {
            "notification_id": request.notification_id,
            "channel": request.channel.value,
            "subject": request.subject,
            "body": request.plain_text_content or request.short_content,
            "html_body": request.html_content,
            "correlation_id": request.correlation_id,
            "metadata": request.metadata,
            "timestamp": time.time(),
        }

    def _build_headers(
        self,
        request: DeliveryRequest,
        payload: dict[str, Any],
    ) -> dict[str, str]:
        """Build the HTTP headers for the webhook request.

        Includes content type, correlation ID, and an HMAC-SHA256
        signature header if a signing secret is configured. The
        signature allows the receiving system to verify the
        authenticity and integrity of the webhook payload.

        Args:
            request: The delivery request.
            payload: The request payload (used for signature computation).

        Returns:
            The headers dictionary for the HTTP request.
        """
        headers = {
            "Content-Type": "application/json",
            "X-Correlation-ID": request.correlation_id,
            "X-Notification-ID": request.notification_id,
            "User-Agent": "NotificationService/1.0",
        }

        if self._signing_secret:
            body = json.dumps(payload, sort_keys=True)
            signature = hmac.new(
                self._signing_secret.encode("utf-8"),
                body.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        return headers

    async def _is_safe_url(self, url: str) -> bool:
        """Validate that a URL is safe for outbound requests (SSRF protection).

        Checks that the URL scheme is http/https and that the hostname
        does not resolve to private, loopback, or reserved IP addresses.

        Args:
            url: The URL to validate.

        Returns:
            True if the URL is considered safe, False otherwise.
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False

            hostname = parsed.hostname
            if not hostname:
                return False

            # Resolve hostname to all associated IP addresses
            loop = asyncio.get_event_loop()
            addr_infos = await loop.run_in_executor(
                None,
                lambda: socket.getaddrinfo(hostname, None)
            )

            for info in addr_infos:
                ip_str = info[4][0]
                ip = ipaddress.ip_address(ip_str)

                # Check for private, loopback, link-local, or reserved addresses
                if (
                    ip.is_private or
                    ip.is_loopback or
                    ip.is_link_local or
                    ip.is_multicast or
                    ip.is_reserved or
                    ip.is_unspecified
                ):
                    return False

            return True

        except Exception as e:
            logger.warning("SSRF validation failed for URL %s: %s", url, e)
            return False
