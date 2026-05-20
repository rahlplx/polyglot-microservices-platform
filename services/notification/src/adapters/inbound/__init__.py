"""
Inbound adapters for the Notification service.

Inbound adapters are driving adapters that translate external requests
(gRPC calls, Kafka events) into domain use case invocations. They handle
protocol-specific concerns like message deserialization, authentication,
and error mapping, keeping the domain layer protocol-agnostic.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.domain.models import (
    Notification, NotificationChannel, NotificationPriority,
)
from src.domain.ports import SendNotificationPort

logger = logging.getLogger(__name__)


class GrpcHandler:
    """gRPC handler for the Notification service query API.
    Implements the QueryNotificationService defined in the Protobuf schema,
    handling status queries and preference management RPCs. The handler
    translates between gRPC message format and domain types, ensuring
    no gRPC-specific concerns leak into the domain layer."""

    def __init__(self, notification_service: SendNotificationPort) -> None:
        self._service = notification_service

    async def get_notification_status(self, notification_id: str) -> Optional[dict[str, Any]]:
        """Handle GetNotificationStatus RPC.
        Returns the current delivery status and metadata for a notification."""
        notification = await self._service.get_status(notification_id)
        if not notification:
            return None
        return {
            "notification_id": notification.id,
            "status": notification.status.value,
            "channel": notification.channel.value,
            "created_at": notification.created_at.isoformat(),
            "sent_at": notification.sent_at.isoformat() if notification.sent_at else None,
            "delivered_at": notification.delivered_at.isoformat() if notification.delivered_at else None,
            "delivery_attempts": notification.delivery_attempts,
        }

    async def get_preferences(self, user_id: str) -> Optional[dict[str, Any]]:
        """Handle GetPreferences RPC.
        Returns notification preferences for a specific user."""
        prefs = await self._service.get_preferences(user_id)
        if not prefs:
            return None
        return {
            "user_id": prefs.user_id,
            "email_enabled": prefs.email_enabled,
            "sms_enabled": prefs.sms_enabled,
            "push_enabled": prefs.push_enabled,
            "quiet_hours_start": prefs.quiet_hours_start,
            "quiet_hours_end": prefs.quiet_hours_end,
            "preferred_channel": prefs.preferred_channel.value,
        }


class KafkaEventConsumer:
    """Kafka consumer for CloudEvents that trigger notification delivery.
    Subscribes to order.events, payment.events, and other business event
    topics. Each event is mapped to a notification template and delivered
    through the notification pipeline. The consumer handles CloudEvents v1.0
    envelope deserialization and implements at-least-once processing semantics
    with manual offset commit after successful notification delivery."""

    def __init__(self, notification_service: SendNotificationPort) -> None:
        self._service = notification_service
        self._running = False

    async def start(self, brokers: str, topics: list[str], group_id: str) -> None:
        """Start consuming events from Kafka topics.
        In production, this uses confluent-kafka or aiokafka for async
        consumption with manual offset management for at-least-once delivery."""
        self._running = True
        logger.info("kafka consumer starting", extra={"brokers": brokers, "topics": topics})

        # In production:
        # consumer = aiokafka.AIOKafkaConsumer(
        #     *topics,
        #     bootstrap_servers=brokers,
        #     group_id=group_id,
        #     enable_auto_commit=False,
        # )
        # async for msg in consumer:
        #     await self._process_event(msg.value)
        #     await consumer.commit()

    async def stop(self) -> None:
        """Gracefully stop the Kafka consumer."""
        self._running = False
        logger.info("kafka consumer stopped")

    async def _process_event(self, event_data: bytes) -> None:
        """Process a single CloudEvent from Kafka.
        Deserializes the CloudEvent envelope, maps it to a notification
        template, and delegates to the notification service for delivery."""
        try:
            event = json.loads(event_data)
        except json.JSONDecodeError:
            logger.error("failed to decode event", extra={"data": event_data[:200]})
            return

        event_type = event.get("type", "")
        data = event.get("data", {})

        # Map event types to notification templates.
        template_map = {
            "com.gstack.order.created": "order-confirmation",
            "com.gstack.payment.completed": "payment-confirmation",
            "com.gstack.payment.failed": "payment-failure",
            "com.gstack.order.shipped": "shipping-update",
        }

        template_id = template_map.get(event_type)
        if not template_id:
            logger.debug("no template for event type", extra={"event_type": event_type})
            return

        notification = Notification(
            recipient_id=data.get("customer_id", ""),
            channel=NotificationChannel.EMAIL,
            template_id=template_id,
            template_vars=data,
            priority=NotificationPriority.NORMAL,
            idempotency_key=event.get("id"),
            metadata={"source_event": event_type, "event_id": event.get("id")},
        )

        await self._service.send(notification)
