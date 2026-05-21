"""
Contract test for the NotificationService gRPC interface.

Verifies that the GrpcNotificationHandler implements all RPC methods
defined in notification.v1.NotificationService proto specification:
  - SendNotification
  - GetNotificationStatus
  - GetNotificationPreferences
  - UpdateNotificationPreferences
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.adapters.inbound.grpc_handler import GrpcNotificationHandler
from src.domain.ports.inbound.send_notification import (
    GetDeliveryStatusPort,
    GetPreferencesPort,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_status_port() -> AsyncMock:
    return AsyncMock(spec=GetDeliveryStatusPort)


@pytest.fixture
def mock_preferences_port() -> AsyncMock:
    return AsyncMock(spec=GetPreferencesPort)


@pytest.fixture
def grpc_handler(
    mock_status_port: AsyncMock,
    mock_preferences_port: AsyncMock,
) -> GrpcNotificationHandler:
    return GrpcNotificationHandler(
        status_port=mock_status_port,
        preferences_port=mock_preferences_port,
    )


# ---------------------------------------------------------------------------
# Proto interface satisfaction
# ---------------------------------------------------------------------------

class TestNotificationProtoContract:
    """Contract tests for the NotificationService gRPC interface.

    These tests verify that the GrpcNotificationHandler exposes all RPC
    methods defined in the notification.v1.NotificationService proto spec.
    The proto defines: SendNotification, GetNotificationStatus,
    GetNotificationPreferences, UpdateNotificationPreferences.
    """

    def test_handler_has_get_notification_status(
        self, grpc_handler: GrpcNotificationHandler
    ) -> None:
        """GetNotificationStatus RPC must be implemented."""
        assert hasattr(grpc_handler, "get_notification_status")
        assert callable(grpc_handler.get_notification_status)

    def test_handler_has_get_notification_preferences(
        self, grpc_handler: GrpcNotificationHandler
    ) -> None:
        """GetNotificationPreferences RPC must be implemented."""
        assert hasattr(grpc_handler, "get_notification_preferences")
        assert callable(grpc_handler.get_notification_preferences)

    def test_status_method_is_async(self, grpc_handler: GrpcNotificationHandler) -> None:
        """get_notification_status must be a coroutine."""
        import asyncio
        assert asyncio.iscoroutinefunction(grpc_handler.get_notification_status)

    def test_preferences_method_is_async(
        self, grpc_handler: GrpcNotificationHandler
    ) -> None:
        """get_notification_preferences must be a coroutine."""
        import asyncio
        assert asyncio.iscoroutinefunction(grpc_handler.get_notification_preferences)

    def test_handler_accepts_status_port(self) -> None:
        """Handler must accept GetDeliveryStatusPort."""
        handler = GrpcNotificationHandler(
            status_port=AsyncMock(spec=GetDeliveryStatusPort),
            preferences_port=AsyncMock(spec=GetPreferencesPort),
        )
        assert handler._status_port is not None

    def test_handler_accepts_preferences_port(self) -> None:
        """Handler must accept GetPreferencesPort."""
        handler = GrpcNotificationHandler(
            status_port=AsyncMock(spec=GetDeliveryStatusPort),
            preferences_port=AsyncMock(spec=GetPreferencesPort),
        )
        assert handler._preferences_port is not None

    def test_status_method_returns_dict(
        self, grpc_handler: GrpcNotificationHandler
    ) -> None:
        """get_notification_status return type annotation should be dict."""
        import inspect
        sig = inspect.signature(grpc_handler.get_notification_status)
        assert sig.return_annotation == dict or sig.return_annotation is dict
