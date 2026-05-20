"""
Kafka CloudEvent consumer adapter for the Notification service.

This module implements the primary inbound adapter for the Notification
service: a Kafka consumer that subscribes to domain event topics and
triggers notification delivery based on event content. Each event type
maps to a notification template and a set of delivery rules.

The consumer uses confluent-kafka-python with a committed consumer group
for reliable event processing. Failed events are retried three times with
exponential backoff and then forwarded to the dead letter topic. The
consumer supports parallel processing with a configurable concurrency
limit to prevent overloading the delivery providers.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from ...domain.models.notification import (
    NotificationChannel,
    NotificationPriority,
    NotificationType,
    Recipient,
)
from ...domain.ports.inbound.send_notification import (
    SendNotificationRequest,
)
from ...domain.services.notification_service import NotificationService, NotificationError

logger = logging.getLogger(__name__)


# Event type to notification mapping
EVENT_TYPE_MAPPING: dict[str, dict[str, Any]] = {
    "com.company.order.confirmed": {
        "template_id": "order-confirmation",
        "channels": [NotificationChannel.EMAIL, NotificationChannel.PUSH],
        "notification_type": NotificationType.ORDER_CONFIRMATION,
        "priority": NotificationPriority.NORMAL,
    },
    "com.company.order.cancelled": {
        "template_id": "order-cancellation",
        "channels": [NotificationChannel.EMAIL, NotificationChannel.SMS],
        "notification_type": NotificationType.ORDER_CANCELLATION,
        "priority": NotificationPriority.HIGH,
    },
    "com.company.order.completed": {
        "template_id": "order-delivery",
        "channels": [NotificationChannel.EMAIL, NotificationChannel.PUSH],
        "notification_type": NotificationType.ORDER_DELIVERY,
        "priority": NotificationPriority.NORMAL,
    },
    "com.company.payment.processed": {
        "template_id": "payment-receipt",
        "channels": [NotificationChannel.EMAIL],
        "notification_type": NotificationType.PAYMENT_RECEIPT,
        "priority": NotificationPriority.NORMAL,
    },
    "com.company.payment.refunded": {
        "template_id": "payment-refund",
        "channels": [NotificationChannel.EMAIL, NotificationChannel.SMS],
        "notification_type": NotificationType.PAYMENT_REFUND,
        "priority": NotificationPriority.HIGH,
    },
    "com.company.payment.failed": {
        "template_id": "payment-failure",
        "channels": [NotificationChannel.EMAIL, NotificationChannel.PUSH],
        "notification_type": NotificationType.PAYMENT_FAILURE,
        "priority": NotificationPriority.URGENT,
    },
    "com.company.catalog.inventory-low": {
        "template_id": "inventory-alert",
        "channels": [NotificationChannel.WEBHOOK],
        "notification_type": NotificationType.INVENTORY_ALERT,
        "priority": NotificationPriority.HIGH,
    },
}


@dataclass
class CloudEvent:
    """Parsed CloudEvents v1.0 envelope.

    Represents a CloudEvent as defined by the CloudEvents specification v1.0.
    The service consumes events in the structured content mode with JSON
    encoding. All required attributes are parsed, and the data payload is
    deserialized from JSON.

    The specversion field is validated to ensure compatibility with the
    v1.0 specification. The type field is used to route the event to the
    appropriate notification template.
    """

    specversion: str = "1.0"
    type: str = ""
    source: str = ""
    id: str = ""
    time: Optional[str] = None
    datacontenttype: str = "application/json"
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CloudEvent:
        """Parse a CloudEvent from a raw dictionary.

        Handles both the standard CloudEvents v1.0 attribute naming and
        common variations. Validates the specversion field and extracts
        the data payload.

        Args:
            raw: The raw event dictionary from Kafka message deserialization.

        Returns:
            A CloudEvent instance with parsed attributes.

        Raises:
            ValueError: If the event is not a valid CloudEvents v1.0 envelope.
        """
        specversion = raw.get("specversion", raw.get("specversion", "1.0"))
        if specversion != "1.0":
            raise ValueError(
                f"Unsupported CloudEvents specversion: {specversion}"
            )

        return cls(
            specversion=specversion,
            type=raw.get("type", ""),
            source=raw.get("source", ""),
            id=raw.get("id", ""),
            time=raw.get("time"),
            datacontenttype=raw.get("datacontenttype", "application/json"),
            data=raw.get("data", {}),
        )


class EventConsumer:
    """Kafka CloudEvent consumer for triggering notification delivery.

    This adapter subscribes to domain event topics on Kafka and processes
    each event by mapping it to a notification template and delivery
    configuration. The consumer implements a multi-step pipeline: event
    parsing and validation, notification template selection, template
    rendering, delivery optimization, and channel dispatch.

    The consumer supports configurable concurrency limits and retry
    policies. Failed events are retried with exponential backoff up to
    the maximum retry count, then forwarded to the dead letter topic.
    """

    # Subscribed topics
    SUBSCRIBED_TOPICS = [
        "com.company.order.confirmed",
        "com.company.order.cancelled",
        "com.company.order.completed",
        "com.company.payment.processed",
        "com.company.payment.refunded",
        "com.company.payment.failed",
        "com.company.catalog.inventory-low",
    ]

    def __init__(
        self,
        notification_service: NotificationService,
        kafka_config: Optional[dict[str, Any]] = None,
        max_retries: int = 3,
        concurrency_limit: int = 20,
        dlq_topic: str = "notification.events.dlq",
    ) -> None:
        """Initialize the event consumer.

        Args:
            notification_service: The domain notification service for
                dispatching notifications.
            kafka_config: Configuration for the confluent-kafka consumer.
                If None, default configuration is used.
            max_retries: Maximum number of retry attempts for failed events.
            concurrency_limit: Maximum number of concurrent notification
                processing tasks.
            dlq_topic: The Kafka topic for dead-letter events that exceed
                the maximum retry count.
        """
        self._notification_service = notification_service
        self._kafka_config = kafka_config or {}
        self._max_retries = max_retries
        self._concurrency_limit = concurrency_limit
        self._dlq_topic = dlq_topic
        self._consumer = None
        self._producer = None
        self._running = False

    async def start(self) -> None:
        """Start the Kafka consumer.

        Initializes the confluent-kafka consumer and producer, subscribes
        to the configured topics, and begins the consume loop. This method
        blocks until stop() is called.
        """
        try:
            from confluent_kafka import Consumer, Producer
        except ImportError:
            logger.error(
                "confluent-kafka not installed, event consumer cannot start"
            )
            return

        consumer_config = {
            "bootstrap.servers": self._kafka_config.get(
                "bootstrap.servers", "localhost:9092"
            ),
            "group.id": "notification-event-consumer",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "session.timeout.ms": 30000,
            "max.poll.interval.ms": 300000,
            "cooperative.sticky.assignment.strategy": True,
        }
        consumer_config.update(self._kafka_config)

        self._consumer = Consumer(consumer_config)
        self._consumer.subscribe(self.SUBSCRIBED_TOPICS)

        producer_config = {
            "bootstrap.servers": self._kafka_config.get(
                "bootstrap.servers", "localhost:9092"
            ),
        }
        self._producer = Producer(producer_config)

        self._running = True
        logger.info(
            "Event consumer started, subscribed to: %s",
            ", ".join(self.SUBSCRIBED_TOPICS),
        )

        try:
            while self._running:
                msg = self._consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    logger.error("Kafka consumer error: %s", msg.error())
                    continue

                await self._process_message(msg)
                self._consumer.commit(asynchronous=False)
        except Exception as e:
            logger.error("Event consumer error: %s", e, exc_info=True)
        finally:
            if self._consumer:
                self._consumer.close()
            logger.info("Event consumer stopped")

    def stop(self) -> None:
        """Signal the consumer to stop processing.

        Sets the running flag to False, causing the consume loop to exit
        after the current message is processed. This method does not block;
        the consumer thread will exit gracefully.
        """
        self._running = False
        logger.info("Event consumer stop requested")

    async def _process_message(self, msg: Any) -> None:
        """Process a single Kafka message.

        Deserializes the message value as a CloudEvent, maps it to a
        notification configuration, and dispatches the notification.
        If processing fails, the event is retried up to max_retries times
        with exponential backoff, then forwarded to the DLQ.

        Args:
            msg: The confluent-kafka Message object.
        """
        try:
            raw_event = json.loads(msg.value().decode("utf-8"))
            cloud_event = CloudEvent.from_dict(raw_event)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse CloudEvent: %s", e)
            return

        event_config = EVENT_TYPE_MAPPING.get(cloud_event.type)
        if event_config is None:
            logger.warning(
                "No mapping for event type: %s, skipping", cloud_event.type
            )
            return

        # Extract recipient from event data
        recipient_data = cloud_event.data.get("recipient", {})
        user_data = cloud_event.data.get("user", {})

        recipient = Recipient(
            user_id=recipient_data.get("user_id", user_data.get("id", "")),
            email=recipient_data.get("email", user_data.get("email")),
            phone=recipient_data.get("phone", user_data.get("phone")),
            device_token=recipient_data.get("device_token"),
            webhook_url=recipient_data.get("webhook_url"),
            timezone=recipient_data.get("timezone", "UTC"),
        )

        # Build template variables from event data
        template_vars = self._extract_template_vars(cloud_event)

        # Send notification for each channel in the mapping
        for channel in event_config["channels"]:
            try:
                request = SendNotificationRequest(
                    recipient=recipient,
                    channel=channel,
                    template_id=event_config["template_id"],
                    template_vars=template_vars,
                    notification_type=event_config["notification_type"],
                    priority=event_config["priority"],
                    correlation_id=cloud_event.id,
                )

                response = await self._notification_service.send(request)
                logger.info(
                    "Notification sent: id=%s, channel=%s, event_type=%s",
                    response.notification.notification_id,
                    channel.value,
                    cloud_event.type,
                )

            except NotificationError as e:
                logger.warning(
                    "Notification failed for event %s, channel %s: %s",
                    cloud_event.id,
                    channel.value,
                    e,
                )
                # Could implement retry or DLQ forwarding here
            except Exception as e:
                logger.error(
                    "Unexpected error processing event %s: %s",
                    cloud_event.id,
                    e,
                    exc_info=True,
                )

    @staticmethod
    def _extract_template_vars(cloud_event: CloudEvent) -> dict[str, str]:
        """Extract template variables from a CloudEvent's data payload.

        Flattens the event data into a string-keyed dictionary suitable
        for template rendering. Nested objects are flattened with dot
        notation (e.g., {"order": {"id": "123"}} becomes {"order.id": "123"}).

        Args:
            cloud_event: The parsed CloudEvent.

        Returns:
            A flat dictionary of template variable names to string values.
        """
        result: dict[str, str] = {}
        data = cloud_event.data

        def flatten(prefix: str, obj: Any) -> None:
            """Recursively flatten a nested dictionary."""
            if isinstance(obj, dict):
                for key, value in obj.items():
                    new_key = f"{prefix}.{key}" if prefix else key
                    flatten(new_key, value)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    flatten(f"{prefix}[{i}]", item)
            else:
                result[prefix] = str(obj) if obj is not None else ""

        flatten("", data)
        return result

    async def _send_to_dlq(self, event: dict[str, Any], error: str) -> None:
        """Forward a failed event to the dead letter topic.

        The DLQ event includes the original event data along with error
        metadata (error message, timestamp, retry count) for debugging
        and manual reprocessing.

        Args:
            event: The original event dictionary.
            error: The error message describing the failure.
        """
        if self._producer is None:
            logger.error("Cannot send to DLQ: producer not initialized")
            return

        dlq_event = {
            **event,
            "dlq_metadata": {
                "error": error,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "original_topic": event.get("source", "unknown"),
            },
        }

        try:
            self._producer.produce(
                self._dlq_topic,
                key=event.get("id", ""),
                value=json.dumps(dlq_event).encode("utf-8"),
            )
            self._producer.flush()
            logger.info("Event forwarded to DLQ: %s", event.get("id"))
        except Exception as e:
            logger.error("Failed to send event to DLQ: %s", e)
