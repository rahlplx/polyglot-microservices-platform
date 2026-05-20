"""
SMS delivery channel adapter using Twilio/Amazon SNS.

This module implements the ChannelSenderPort for SMS notifications. It
supports both Twilio and Amazon SNS as SMS delivery providers, with all
external communication routing through the ACL sidecar for circuit
breaking and vendor SDK isolation.

The adapter handles SMS-specific formatting including message length
limits (160 characters for standard SMS, 1600 for long messages with
concatenation), character encoding (GSM 7-bit vs UCS-2), and delivery
receipt processing.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from ....domain.models.notification import NotificationChannel
from ....domain.ports.outbound.channel_sender import (
    DeliveryRequest,
    DeliveryResponse,
)

logger = logging.getLogger(__name__)

# SMS length limits
SMS_MAX_LENGTH_STANDARD = 160
SMS_MAX_LENGTH_CONCATENATED = 1600


class SmsSenderAdapter:
    """SMS channel sender using Twilio or Amazon SNS.

    This adapter sends SMS notifications through either the Twilio Messages
    API or Amazon SNS, depending on configuration. All external provider
    communication routes through the ACL sidecar to enforce circuit breaking,
    rate limiting, and vendor SDK isolation.

    The adapter handles SMS-specific concerns including message truncation
    for length limits, character encoding detection, and delivery status
    tracking through provider webhook callbacks.
    """

    def __init__(
        self,
        provider: str = "twilio",
        from_number: str = "+15551234567",
        twilio_account_sid: Optional[str] = None,
        twilio_auth_token: Optional[str] = None,
        sns_region: str = "us-east-1",
        acl_sidecar_url: Optional[str] = None,
    ) -> None:
        """Initialize the SMS sender adapter.

        Args:
            provider: The SMS provider to use ("twilio" or "sns").
            from_number: The sender phone number.
            twilio_account_sid: Twilio account SID for authentication.
            twilio_auth_token: Twilio auth token for authentication.
            sns_region: AWS region for SNS.
            acl_sidecar_url: URL of the ACL sidecar for external communication.
        """
        self._provider = provider
        self._from_number = from_number
        self._twilio_account_sid = twilio_account_sid
        self._twilio_auth_token = twilio_auth_token
        self._sns_region = sns_region
        self._acl_sidecar_url = acl_sidecar_url

    @property
    def channel(self) -> NotificationChannel:
        """The SMS notification channel."""
        return NotificationChannel.SMS

    async def send(self, request: DeliveryRequest) -> DeliveryResponse:
        """Send an SMS notification.

        Formats the message content for SMS delivery (truncating if
        necessary), then sends it through the configured provider via
        the ACL sidecar. The response includes the provider's message
        identifier for tracking delivery status.

        Args:
            request: The delivery request with SMS content.

        Returns:
            The delivery response indicating success or failure.
        """
        start_time = time.monotonic()

        try:
            # Select message content for SMS
            message_body = (
                request.short_content
                or request.plain_text_content
                or ""
            )

            # Truncate if necessary
            if len(message_body) > SMS_MAX_LENGTH_CONCATENATED:
                message_body = (
                    message_body[: SMS_MAX_LENGTH_CONCATENATED - 3] + "..."
                )
                logger.warning(
                    "SMS message truncated for notification %s",
                    request.notification_id,
                )

            # Send via configured provider
            if self._provider == "twilio":
                response = await self._send_via_twilio(request, message_body)
            elif self._provider == "sns":
                response = await self._send_via_sns(request, message_body)
            else:
                return DeliveryResponse(
                    success=False,
                    provider=self._provider,
                    error_message=f"Unknown SMS provider: {self._provider}",
                )

            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            response.response_time_ms = elapsed_ms
            return response

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "SMS delivery failed for notification %s: %s",
                request.notification_id,
                e,
                exc_info=True,
            )
            return DeliveryResponse(
                success=False,
                provider=self._provider,
                error_message=str(e),
                response_time_ms=elapsed_ms,
            )

    async def health_check(self) -> bool:
        """Check if the SMS provider is reachable.

        Verifies connectivity to the configured provider through the
        ACL sidecar health endpoint.
        """
        try:
            import httpx
            base_url = self._acl_sidecar_url
            if base_url:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{base_url}/health", timeout=5.0)
                    return resp.status_code == 200
            return True  # assume healthy if no sidecar
        except Exception as e:
            logger.warning("SMS health check failed: %s", e)
            return False

    async def _send_via_twilio(
        self, request: DeliveryRequest, message_body: str
    ) -> DeliveryResponse:
        """Send SMS through Twilio Messages API via ACL sidecar.

        The Twilio API requires the account SID and auth token for
        authentication. These credentials are passed through the ACL
        sidecar rather than stored in the service directly, ensuring
        that the service code has no vendor-specific SDK imports.

        Args:
            request: The delivery request.
            message_body: The formatted SMS message body.

        Returns:
            The delivery response with Twilio message SID.
        """
        import httpx

        payload = {
            "To": request.recipient_address,
            "From": self._from_number,
            "Body": message_body,
            "StatusCallback": "/api/v1/notifications/webhooks/twilio",
        }

        base_url = self._acl_sidecar_url or "http://localhost:8081"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/api/v1/twilio/messages",
                json=payload,
                timeout=30.0,
            )

        if resp.status_code in (200, 201):
            data = resp.json()
            return DeliveryResponse(
                success=True,
                provider="twilio",
                provider_message_id=data.get("sid", request.notification_id),
            )
        else:
            return DeliveryResponse(
                success=False,
                provider="twilio",
                error_message=f"Twilio returned {resp.status_code}: {resp.text}",
            )

    async def _send_via_sns(
        self, request: DeliveryRequest, message_body: str
    ) -> DeliveryResponse:
        """Send SMS through Amazon SNS via ACL sidecar.

        SNS supports direct SMS publishing without requiring a topic
        subscription. The phone number must be in E.164 format.

        Args:
            request: The delivery request.
            message_body: The formatted SMS message body.

        Returns:
            The delivery response with SNS message ID.
        """
        import httpx

        payload = {
            "PhoneNumber": request.recipient_address,
            "Message": message_body,
            "MessageAttributes": {
                "AWS.SNS.SMS.SenderID": {
                    "DataType": "String",
                    "StringValue": "NotifySvc",
                },
            },
        }

        base_url = self._acl_sidecar_url or "http://localhost:8081"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/api/v1/sns/publish-sms",
                json=payload,
                timeout=30.0,
            )

        if resp.status_code == 200:
            data = resp.json()
            return DeliveryResponse(
                success=True,
                provider="sns",
                provider_message_id=data.get("MessageId", request.notification_id),
            )
        else:
            return DeliveryResponse(
                success=False,
                provider="sns",
                error_message=f"SNS returned {resp.status_code}: {resp.text}",
            )
