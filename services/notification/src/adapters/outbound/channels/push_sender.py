"""
Push notification channel adapter using Firebase Cloud Messaging (FCM) / APNs.

This module implements the ChannelSenderPort for push notifications. It
supports both Firebase Cloud Messaging (for Android and web) and Apple
Push Notification service (for iOS). All external provider communication
routes through the ACL sidecar.

The adapter handles push-specific formatting including notification
payload structure, badge counts, sound settings, and deep link
configuration. It supports both data messages and notification messages
as defined by the FCM HTTP v1 API.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from ....domain.models.notification import NotificationChannel
from ....domain.ports.outbound.channel_sender import (
    ChannelSenderPort,
    DeliveryRequest,
    DeliveryResponse,
)

logger = logging.getLogger(__name__)


class PushSenderAdapter:
    """Push notification channel sender using FCM and APNs.

    This adapter sends push notifications through Firebase Cloud Messaging
    (FCM) for Android and web clients, and Apple Push Notification service
    (APNs) for iOS clients. The adapter determines which service to use
    based on the device token format, routing FCM tokens to the FCM API
    and APNs tokens to the APNs API.

    All external communication routes through the ACL sidecar for circuit
    breaking, rate limiting, and vendor SDK isolation. The adapter
    constructs provider-specific payload formats and handles delivery
    receipt processing.
    """

    def __init__(
        self,
        fcm_project_id: Optional[str] = None,
        fcm_service_account_key: Optional[str] = None,
        apns_cert_path: Optional[str] = None,
        apns_key_id: Optional[str] = None,
        apns_team_id: Optional[str] = None,
        acl_sidecar_url: Optional[str] = None,
    ) -> None:
        """Initialize the push notification sender adapter.

        Args:
            fcm_project_id: Google Cloud project ID for FCM.
            fcm_service_account_key: Path to FCM service account key file.
            apns_cert_path: Path to APNs certificate file.
            apns_key_id: APNs authentication key ID.
            apns_team_id: Apple developer team ID.
            acl_sidecar_url: URL of the ACL sidecar for external communication.
        """
        self._fcm_project_id = fcm_project_id
        self._fcm_service_account_key = fcm_service_account_key
        self._apns_cert_path = apns_cert_path
        self._apns_key_id = apns_key_id
        self._apns_team_id = apns_team_id
        self._acl_sidecar_url = acl_sidecar_url

    @property
    def channel(self) -> NotificationChannel:
        """The push notification channel."""
        return NotificationChannel.PUSH

    async def send(self, request: DeliveryRequest) -> DeliveryResponse:
        """Send a push notification.

        Determines the target platform based on the device token format
        and routes the notification to the appropriate provider (FCM or
        APNs) through the ACL sidecar. The response includes the
        provider's message identifier for tracking.

        Args:
            request: The delivery request with push notification content.

        Returns:
            The delivery response indicating success or failure.
        """
        start_time = time.monotonic()

        try:
            # Determine provider based on token format
            # FCM tokens are typically long strings, APNs tokens are hex
            device_token = request.recipient_address
            if self._is_apns_token(device_token):
                response = await self._send_via_apns(request)
            else:
                response = await self._send_via_fcm(request)

            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            response.response_time_ms = elapsed_ms
            return response

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "Push delivery failed for notification %s: %s",
                request.notification_id,
                e,
                exc_info=True,
            )
            return DeliveryResponse(
                success=False,
                provider="fcm",
                error_message=str(e),
                response_time_ms=elapsed_ms,
            )

    async def health_check(self) -> bool:
        """Check if the push notification service is reachable.

        Verifies connectivity to the FCM or APNs service through the
        ACL sidecar health endpoint.
        """
        try:
            import httpx
            base_url = self._acl_sidecar_url
            if base_url:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{base_url}/health", timeout=5.0)
                    return resp.status_code == 200
            return True
        except Exception as e:
            logger.warning("Push health check failed: %s", e)
            return False

    @staticmethod
    def _is_apns_token(token: str) -> bool:
        """Determine if a device token is an APNs token.

        APNs tokens are 64-character hexadecimal strings. FCM tokens
        are typically longer and contain alphanumeric characters. This
        heuristic is used to route notifications to the correct provider.

        Args:
            token: The device token string.

        Returns:
            True if the token appears to be an APNs token.
        """
        return len(token) == 64 and all(c in "0123456789abcdefABCDEF" for c in token)

    async def _send_via_fcm(self, request: DeliveryRequest) -> DeliveryResponse:
        """Send push notification through Firebase Cloud Messaging.

        Constructs an FCM HTTP v1 API message payload and sends it
        through the ACL sidecar. The payload includes both a
        notification object (for automatic display) and a data object
        (for custom handling by the client app).

        Args:
            request: The delivery request.

        Returns:
            The delivery response with FCM message ID.
        """
        import httpx

        # Build FCM message payload (HTTP v1 API format)
        payload = {
            "message": {
                "token": request.recipient_address,
                "notification": {
                    "title": request.subject or "Notification",
                    "body": request.short_content or request.plain_text_content or "",
                },
                "data": {
                    "notification_id": request.notification_id,
                    "correlation_id": request.correlation_id,
                },
                "android": {
                    "priority": "high" if request.metadata.get("priority") == "urgent" else "normal",
                },
                "apns": {
                    "payload": {
                        "aps": {
                            "badge": 1,
                            "sound": "default",
                        },
                    },
                },
            },
        }

        project_id = self._fcm_project_id or "default-project"
        base_url = self._acl_sidecar_url or "http://localhost:8081"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/api/v1/fcm/projects/{project_id}/messages:send",
                json=payload,
                timeout=30.0,
            )

        if resp.status_code == 200:
            data = resp.json()
            return DeliveryResponse(
                success=True,
                provider="fcm",
                provider_message_id=data.get("name", request.notification_id),
            )
        else:
            return DeliveryResponse(
                success=False,
                provider="fcm",
                error_message=f"FCM returned {resp.status_code}: {resp.text}",
            )

    async def _send_via_apns(self, request: DeliveryRequest) -> DeliveryResponse:
        """Send push notification through Apple Push Notification service.

        Constructs an APNs payload and sends it through the ACL sidecar.
        The APNs payload includes the alert, badge, and sound fields as
        defined by the Apple Push Notification API.

        Args:
            request: The delivery request.

        Returns:
            The delivery response with APNs result.
        """
        import httpx

        payload = {
            "device_token": request.recipient_address,
            "payload": {
                "aps": {
                    "alert": {
                        "title": request.subject or "Notification",
                        "body": request.short_content or request.plain_text_content or "",
                    },
                    "badge": 1,
                    "sound": "default",
                },
                "notification_id": request.notification_id,
                "correlation_id": request.correlation_id,
            },
            "push_type": "alert",
            "priority": 10,  # immediate
        }

        base_url = self._acl_sidecar_url or "http://localhost:8081"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/api/v1/apns/push",
                json=payload,
                timeout=30.0,
            )

        if resp.status_code == 200:
            return DeliveryResponse(
                success=True,
                provider="apns",
                provider_message_id=request.notification_id,
            )
        else:
            return DeliveryResponse(
                success=False,
                provider="apns",
                error_message=f"APNs returned {resp.status_code}: {resp.text}",
            )
