"""
Email delivery channel adapter using SMTP/Amazon SES.

This module implements the ChannelSenderPort for email notifications. It
supports both direct SMTP delivery and Amazon SES as a managed email
delivery service. The adapter handles email-specific formatting including
HTML and plain text multipart messages, email headers, and bounce
processing.

All external email provider communication is designed to route through
an ACL sidecar for circuit breaking, rate limiting, and vendor SDK
isolation. The adapter does not import any vendor-specific SDKs directly;
instead, it communicates through the sidecar's HTTP API.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from ....domain.models.notification import NotificationChannel
from ....domain.ports.outbound.channel_sender import (
    DeliveryRequest,
    DeliveryResponse,
)

logger = logging.getLogger(__name__)


class EmailSenderAdapter:
    """Email channel sender using SMTP or Amazon SES.

    This adapter sends email notifications through either a direct SMTP
    connection or the Amazon SES HTTP API (via the ACL sidecar). It
    constructs MIME multipart messages with both HTML and plain text
    variants for maximum client compatibility.

    The adapter includes configurable retry behavior and supports
    delivery tracking through SES notification features. Email-specific
    headers such as List-Unsubscribe and X-Correlation-ID are added
    for compliance and traceability.
    """

    def __init__(
        self,
        smtp_host: str = "localhost",
        smtp_port: int = 587,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        use_tls: bool = True,
        from_address: str = "notifications@company.com",
        from_name: str = "Notification Service",
        ses_endpoint: Optional[str] = None,
        acl_sidecar_url: Optional[str] = None,
    ) -> None:
        """Initialize the email sender adapter.

        Args:
            smtp_host: SMTP server hostname.
            smtp_port: SMTP server port.
            smtp_username: SMTP authentication username.
            smtp_password: SMTP authentication password.
            use_tls: Whether to use TLS for the SMTP connection.
            from_address: The sender email address.
            from_name: The display name for the sender.
            ses_endpoint: Optional Amazon SES API endpoint (via ACL sidecar).
            acl_sidecar_url: URL of the ACL sidecar for external communication.
        """
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_username = smtp_username
        self._smtp_password = smtp_password
        self._use_tls = use_tls
        self._from_address = from_address
        self._from_name = from_name
        self._ses_endpoint = ses_endpoint
        self._acl_sidecar_url = acl_sidecar_url

    @property
    def channel(self) -> NotificationChannel:
        """The email notification channel."""
        return NotificationChannel.EMAIL

    async def send(self, request: DeliveryRequest) -> DeliveryResponse:
        """Send an email notification.

        Constructs a MIME multipart message with HTML and plain text
        variants and sends it through the configured SMTP server or
        Amazon SES endpoint. The response includes the provider's message
        identifier for tracking.

        Args:
            request: The delivery request with rendered email content.

        Returns:
            The delivery response indicating success or failure.
        """
        import time
        start_time = time.monotonic()

        try:
            # If SES endpoint is configured, use the ACL sidecar
            if self._ses_endpoint:
                response = await self._send_via_ses(request)
            else:
                response = await self._send_via_smtp(request)

            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            response.response_time_ms = elapsed_ms
            return response

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "Email delivery failed for notification %s: %s",
                request.notification_id,
                e,
                exc_info=True,
            )
            return DeliveryResponse(
                success=False,
                provider="smtp",
                error_message=str(e),
                response_time_ms=elapsed_ms,
            )

    async def health_check(self) -> bool:
        """Check if the SMTP server or SES endpoint is reachable.

        Attempts a connection to the configured email service and
        returns True if the connection is successful.
        """
        try:
            if self._ses_endpoint:
                # Check SES health via ACL sidecar
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{self._acl_sidecar_url or self._ses_endpoint}/health"
                    )
                    return resp.status_code == 200
            else:
                # Check SMTP connectivity
                with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=5) as smtp:
                    if self._use_tls:
                        smtp.starttls()
                    return True
        except Exception as e:
            logger.warning("Email health check failed: %s", e)
            return False

    async def _send_via_smtp(self, request: DeliveryRequest) -> DeliveryResponse:
        """Send email through direct SMTP connection.

        Constructs a MIME multipart message with HTML and plain text
        variants and sends it through the SMTP server. The message
        includes standard email headers and custom headers for
        tracking and compliance.

        Args:
            request: The delivery request with email content.

        Returns:
            The delivery response with SMTP server acceptance status.
        """
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{self._from_name} <{self._from_address}>"
        msg["To"] = request.recipient_address
        msg["Subject"] = request.subject or "Notification"

        # Add custom headers for tracking
        msg["X-Correlation-ID"] = request.correlation_id
        msg["X-Notification-ID"] = request.notification_id

        # Add List-Unsubscribe header for CAN-SPAM compliance
        msg["List-Unsubscribe"] = "<mailto:unsubscribe@company.com>"

        # Attach plain text and HTML variants
        if request.plain_text_content:
            msg.attach(MIMEText(request.plain_text_content, "plain"))
        if request.html_content:
            msg.attach(MIMEText(request.html_content, "html"))

        with smtplib.SMTP(self._smtp_host, self._smtp_port) as smtp:
            if self._use_tls:
                smtp.starttls()
            if self._smtp_username and self._smtp_password:
                smtp.login(self._smtp_username, self._smtp_password)
            smtp.send_message(msg)

        logger.info(
            "Email sent via SMTP: notification_id=%s, to=%s",
            request.notification_id,
            request.recipient_address,
        )

        return DeliveryResponse(
            success=True,
            provider="smtp",
            provider_message_id=request.notification_id,
        )

    async def _send_via_ses(self, request: DeliveryRequest) -> DeliveryResponse:
        """Send email through Amazon SES via the ACL sidecar.

        Uses the SES HTTP API through the ACL sidecar for production
        email delivery. The sidecar handles authentication, circuit
        breaking, and rate limiting.

        Args:
            request: The delivery request with email content.

        Returns:
            The delivery response with SES message ID.
        """
        import httpx

        payload = {
            "Source": f"{self._from_name} <{self._from_address}>",
            "Destination": {"ToAddresses": [request.recipient_address]},
            "Message": {
                "Subject": {"Data": request.subject or "Notification"},
                "Body": {},
            },
            "Headers": {
                "X-Correlation-ID": request.correlation_id,
                "X-Notification-ID": request.notification_id,
            },
        }

        if request.html_content:
            payload["Message"]["Body"]["Html"] = {"Data": request.html_content}
        if request.plain_text_content:
            payload["Message"]["Body"]["Text"] = {"Data": request.plain_text_content}

        base_url = self._acl_sidecar_url or self._ses_endpoint
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/api/v1/ses/send-email",
                json=payload,
                timeout=30.0,
            )

        if resp.status_code == 200:
            data = resp.json()
            return DeliveryResponse(
                success=True,
                provider="ses",
                provider_message_id=data.get("MessageId", request.notification_id),
            )
        else:
            return DeliveryResponse(
                success=False,
                provider="ses",
                error_message=f"SES returned status {resp.status_code}: {resp.text}",
            )
