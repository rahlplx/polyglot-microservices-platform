"""
gRPC query handler for the Notification service.

This module implements the gRPC server adapter that handles synchronous
query requests for notification delivery status and preferences. While the
Notification service is primarily event-driven, the gRPC interface supports
operational queries from the Gateway service and internal tooling.

The handler translates gRPC request messages into domain service calls and
maps domain responses back to gRPC response messages. It includes
interceptors for authentication, logging, and OpenTelemetry tracing.
"""

from __future__ import annotations

import logging
from typing import Optional

from ...domain.models.delivery import DeliveryStatus
from ...domain.models.notification import NotificationChannel
from ...domain.ports.inbound.send_notification import (
    GetDeliveryStatusPort,
    GetDeliveryStatusRequest,
    GetDeliveryStatusResponse,
    GetPreferencesPort,
    GetPreferencesRequest,
    GetPreferencesResponse,
)
from ...domain.services.notification_service import NotificationNotFoundError

logger = logging.getLogger(__name__)


class GrpcNotificationHandler:
    """gRPC handler for notification query operations.

    This adapter implements the gRPC service methods defined in the
    notification.proto specification. It handles GetNotificationStatus and
    GetNotificationPreferences RPCs by delegating to the corresponding
    domain service ports.

    The handler includes error mapping from domain exceptions to gRPC
    status codes, ensuring that clients receive appropriate error responses.
    All operations are traced with OpenTelemetry for observability.
    """

    def __init__(
        self,
        status_port: GetDeliveryStatusPort,
        preferences_port: GetPreferencesPort,
    ) -> None:
        """Initialize the gRPC handler with domain service ports.

        Args:
            status_port: Port for querying notification delivery status.
            preferences_port: Port for querying notification preferences.
        """
        self._status_port = status_port
        self._preferences_port = preferences_port

    async def get_notification_status(
        self,
        notification_id: str,
        include_tracking_details: bool = False,
    ) -> dict:
        """Handle the GetNotificationStatus gRPC request.

        Translates the gRPC request into a domain service call and maps
        the response to a gRPC-compatible dictionary. If the notification
        is not found, returns an error response with NOT_FOUND status.

        Args:
            notification_id: The unique identifier of the notification.
            include_tracking_details: Whether to include full tracking
                event details in the response.

        Returns:
            A dictionary representation of the gRPC response with
            notification status and tracking information.
        """
        logger.info(
            "gRPC GetNotificationStatus request: id=%s, details=%s",
            notification_id,
            include_tracking_details,
        )

        try:
            request = GetDeliveryStatusRequest(
                notification_id=notification_id,
                include_tracking_details=include_tracking_details,
            )
            response = await self._status_port.get_status(request)

            # Map domain response to gRPC-compatible dict
            result = {
                "notification_id": response.notification_id,
                "status": response.status.value,
                "channel": response.channel,
                "recipient_id": response.recipient_id,
                "sent_at": response.sent_at.isoformat() if response.sent_at else None,
                "delivered_at": response.delivered_at.isoformat() if response.delivered_at else None,
                "opened_at": response.opened_at.isoformat() if response.opened_at else None,
                "clicked_at": response.clicked_at.isoformat() if response.clicked_at else None,
                "bounced_at": response.bounced_at.isoformat() if response.bounced_at else None,
            }

            if include_tracking_details:
                result["tracking_details"] = [
                    {
                        "event_type": event.event_type.value,
                        "timestamp": event.timestamp.isoformat(),
                        "provider": event.provider,
                        "metadata": event.metadata,
                    }
                    for event in response.tracking_details
                ]

            return result

        except NotificationNotFoundError as e:
            logger.warning("Notification not found: %s", notification_id)
            return {
                "error": "NOT_FOUND",
                "message": str(e),
            }
        except Exception as e:
            logger.error(
                "Error handling GetNotificationStatus: %s", e, exc_info=True
            )
            return {
                "error": "INTERNAL",
                "message": "Internal server error",
            }

    async def get_notification_preferences(
        self,
        user_id: str,
    ) -> dict:
        """Handle the GetNotificationPreferences gRPC request.

        Retrieves the notification preferences for a user, including
        per-channel opt-in status and quiet hours configuration.

        Args:
            user_id: The user's unique identifier.

        Returns:
            A dictionary representation of the gRPC response with
            user notification preferences.
        """
        logger.info(
            "gRPC GetNotificationPreferences request: user_id=%s",
            user_id,
        )

        try:
            request = GetPreferencesRequest(recipient_id=user_id)
            response = await self._preferences_port.get_preferences(request)

            preference = response.preference
            result = {
                "user_id": preference.recipient_id,
                "global_opt_out": preference.global_opt_out,
                "timezone": preference.timezone,
                "channels": [
                    {
                        "channel": ch.channel,
                        "enabled": ch.enabled,
                        "opt_in_status": ch.opt_in_status.value,
                    }
                    for ch in preference.channel_preferences
                ],
            }

            if preference.quiet_hours:
                result["quiet_hours"] = {
                    "start_time": preference.quiet_hours.start_time.strftime("%H:%M"),
                    "end_time": preference.quiet_hours.end_time.strftime("%H:%M"),
                    "timezone": preference.quiet_hours.timezone,
                }

            return result

        except Exception as e:
            logger.error(
                "Error handling GetNotificationPreferences: %s",
                e,
                exc_info=True,
            )
            return {
                "error": "INTERNAL",
                "message": "Internal server error",
            }
