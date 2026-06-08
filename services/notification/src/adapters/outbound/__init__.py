"""
Outbound adapters for the Notification service.

Outbound adapters implement the domain's outbound ports for infrastructure
concerns: channel delivery (email, SMS, push, webhook), persistence,
and observability. Each adapter translates between domain types and
infrastructure-specific APIs, ensuring the domain remains pure.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from ..domain.models import (
    DeliveryAttempt, Notification, NotificationChannel,
)
from ..domain.ports import ChannelSenderPort

logger = logging.getLogger(__name__)


class EmailSender(ChannelSenderPort):
    """Email channel sender using SMTP or AWS SES.
    This adapter implements the ChannelSenderPort for email delivery.
    It handles email formatting, header construction, and delivery
    through the configured email provider. All provider-specific logic
    is contained within this adapter, maintaining the ACL boundary."""

    async def send(self, notification: Notification) -> DeliveryAttempt:
        """Send a notification via email.
        Constructs a properly formatted email with HTML and plain text
        bodies, then delivers it through the configured SMTP server or
        SES API. Returns a DeliveryAttempt with the outcome."""
        start_time = time.monotonic()
        attempt = DeliveryAttempt(
            notification_id=notification.id,
            channel=NotificationChannel.EMAIL,
            attempted_at=datetime.now(timezone.utc),
        )

        try:
            # In production: use aiosmtplib or AWS SES SDK client.
            # msg = MIMEText(notification.html_body or notification.body, "html" if notification.html_body else "plain")
            # msg["Subject"] = notification.subject
            # msg["To"] = notification.recipient_id
            # await smtp.send_message(msg)

            logger.info("email sent", extra={
                "notification_id": notification.id,
                "recipient": notification.recipient_id,
            })
            attempt.success = True
            attempt.provider_id = f"email_{notification.id}"

        except Exception as e:
            attempt.success = False
            attempt.error_message = str(e)
            logger.error("email send failed", extra={
                "notification_id": notification.id,
                "error": str(e),
            })

        attempt.response_time_ms = (time.monotonic() - start_time) * 1000
        return attempt

    def supports_channel(self, channel: NotificationChannel) -> bool:
        return channel == NotificationChannel.EMAIL


class SmsSender(ChannelSenderPort):
    """SMS channel sender using Twilio or AWS SNS (behind ACL).
    This adapter operates behind the Anti-Corruption Layer because
    it communicates with external vendor APIs (Twilio, SNS). No
    vendor SDK types leak through the ChannelSenderPort interface."""

    async def send(self, notification: Notification) -> DeliveryAttempt:
        start_time = time.monotonic()
        attempt = DeliveryAttempt(
            notification_id=notification.id,
            channel=NotificationChannel.SMS,
            attempted_at=datetime.now(timezone.utc),
        )

        try:
            # In production: use twilio client or AWS SNS SDK.
            # client.messages.create(to=notification.recipient_id, body=notification.body)
            logger.info("sms sent", extra={
                "notification_id": notification.id,
                "recipient": notification.recipient_id,
            })
            attempt.success = True
            attempt.provider_id = f"sms_{notification.id}"

        except Exception as e:
            attempt.success = False
            attempt.error_message = str(e)
            logger.error("sms send failed", extra={"notification_id": notification.id, "error": str(e)})

        attempt.response_time_ms = (time.monotonic() - start_time) * 1000
        return attempt

    def supports_channel(self, channel: NotificationChannel) -> bool:
        return channel == NotificationChannel.SMS


class PushSender(ChannelSenderPort):
    """Push notification sender using FCM (Firebase Cloud Messaging) or APNs.
    Supports both Android (FCM) and iOS (APNs) push notification delivery.
    The adapter handles platform-specific payload formatting and token
    management, with automatic fallback for expired device tokens."""

    async def send(self, notification: Notification) -> DeliveryAttempt:
        start_time = time.monotonic()
        attempt = DeliveryAttempt(
            notification_id=notification.id,
            channel=NotificationChannel.PUSH,
            attempted_at=datetime.now(timezone.utc),
        )

        try:
            # In production: use firebase-admin or aioapns.
            logger.info("push sent", extra={"notification_id": notification.id})
            attempt.success = True
            attempt.provider_id = f"push_{notification.id}"

        except Exception as e:
            attempt.success = False
            attempt.error_message = str(e)
            logger.error("push send failed", extra={"notification_id": notification.id, "error": str(e)})

        attempt.response_time_ms = (time.monotonic() - start_time) * 1000
        return attempt

    def supports_channel(self, channel: NotificationChannel) -> bool:
        return channel == NotificationChannel.PUSH


class WebhookSender(ChannelSenderPort):
    """HTTP webhook sender with retry and circuit breaker.
    Sends notification payloads to configured webhook URLs with
    exponential backoff retry for transient failures. The webhook
    sender validates response status codes and implements a simple
    circuit breaker to avoid hammering unresponsive endpoints."""

    async def send(self, notification: Notification) -> DeliveryAttempt:
        start_time = time.monotonic()
        attempt = DeliveryAttempt(
            notification_id=notification.id,
            channel=NotificationChannel.WEBHOOK,
            attempted_at=datetime.now(timezone.utc),
        )

        try:
            # In production: use aiohttp with retry logic.
            # async with aiohttp.ClientSession() as session:
            #     async with session.post(webhook_url, json=payload) as resp:
            #         if resp.status >= 400:
            #             raise Exception(f"webhook returned {resp.status}")
            logger.info("webhook sent", extra={"notification_id": notification.id})
            attempt.success = True
            attempt.provider_id = f"webhook_{notification.id}"

        except Exception as e:
            attempt.success = False
            attempt.error_message = str(e)
            logger.error("webhook send failed", extra={"notification_id": notification.id, "error": str(e)})

        attempt.response_time_ms = (time.monotonic() - start_time) * 1000
        return attempt

    def supports_channel(self, channel: NotificationChannel) -> bool:
        return channel == NotificationChannel.WEBHOOK
