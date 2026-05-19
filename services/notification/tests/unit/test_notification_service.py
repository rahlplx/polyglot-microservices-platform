"""
Unit tests for NotificationService.

Tests the core notification orchestration service with mocked channel senders.
Validates send_notification, preference management, and delivery optimization.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.models.notification import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
    NotificationType,
    Recipient,
)
from src.domain.models.delivery import DeliveryAttempt, DeliveryReceipt, DeliveryStatus
from src.domain.models.template import RenderedTemplate
from src.domain.models.preference import NotificationPreference
from src.domain.ports.outbound.channel_sender import DeliveryRequest, DeliveryResponse
from src.domain.services.notification_service import (
    ChannelUnavailableError,
    NotificationService,
    NotificationNotFoundError,
    RecipientOptedOutError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_delivery_tracker() -> AsyncMock:
    tracker = AsyncMock()
    tracker.find_by_correlation_id.return_value = None
    tracker.save.side_effect = lambda n: n
    tracker.save_delivery_attempt.return_value = None
    return tracker


@pytest.fixture
def mock_template_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_preference_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_email_sender() -> AsyncMock:
    sender = AsyncMock()
    sender.channel = NotificationChannel.EMAIL
    sender.send.return_value = DeliveryResponse(
        success=True,
        provider="ses",
        provider_message_id="msg-123",
    )
    return sender


@pytest.fixture
def mock_sms_sender() -> AsyncMock:
    sender = AsyncMock()
    sender.channel = NotificationChannel.SMS
    sender.send.return_value = DeliveryResponse(
        success=True,
        provider="twilio",
        provider_message_id="msg-456",
    )
    return sender


@pytest.fixture
def channel_senders(
    mock_email_sender: AsyncMock, mock_sms_sender: AsyncMock
) -> dict[NotificationChannel, AsyncMock]:
    return {
        NotificationChannel.EMAIL: mock_email_sender,
        NotificationChannel.SMS: mock_sms_sender,
    }


@pytest.fixture
def mock_delivery_optimizer() -> AsyncMock:
    optimizer = AsyncMock()

    class Optimization:
        should_defer = False
        optimal_time = None

    optimizer.optimize_delivery_time.return_value = Optimization()
    optimizer.select_channel.return_value = NotificationChannel.EMAIL
    return optimizer


@pytest.fixture
def mock_template_service() -> AsyncMock:
    service = AsyncMock()
    service.render.return_value = RenderedTemplate(
        subject="Test Subject",
        plain_text_content="Test body",
        html_content="<p>Test body</p>",
        short_content="Test",
    )
    return service


@pytest.fixture
def mock_preference_service() -> AsyncMock:
    service = AsyncMock()

    class MockPreference(NotificationPreference):
        recipient_id: str = "user-1"
        channel_preferences: list = []
        quiet_hours = None
        timezone: str = "UTC"
        global_opt_out: bool = False

        def is_channel_enabled(self, channel: str) -> bool:
            return True

        def is_in_quiet_hours(self, hour: int, minute: int) -> bool:
            return False

    pref = MockPreference()
    service.get_preference.return_value = pref
    return service


@pytest.fixture
def notification_service(
    mock_delivery_tracker: AsyncMock,
    mock_template_repo: AsyncMock,
    mock_preference_repo: AsyncMock,
    channel_senders: dict,
    mock_delivery_optimizer: AsyncMock,
    mock_template_service: AsyncMock,
    mock_preference_service: AsyncMock,
) -> NotificationService:
    return NotificationService(
        delivery_tracker=mock_delivery_tracker,
        template_repo=mock_template_repo,
        preference_repo=mock_preference_repo,
        channel_senders=channel_senders,
        delivery_optimizer=mock_delivery_optimizer,
        template_service=mock_template_service,
        preference_service=mock_preference_service,
    )


def _make_send_request(**overrides):
    """Create a SendNotificationRequest for testing."""
    from src.domain.ports.inbound.send_notification import (
        SendNotificationRequest,
        SendNotificationResponse,
    )
    defaults = {
        "recipient": Recipient(
            user_id="user-1",
            email="user@example.com",
            phone="+1234567890",
        ),
        "channel": NotificationChannel.EMAIL,
        "notification_type": NotificationType.ORDER_CONFIRMATION,
        "priority": NotificationPriority.NORMAL,
        "template_id": "order-confirmation",
        "template_vars": {"order_id": "ORD-123"},
        "correlation_id": None,
    }
    defaults.update(overrides)
    return SendNotificationRequest(**defaults)


# ---------------------------------------------------------------------------
# send_notification
# ---------------------------------------------------------------------------

class TestSendNotification:
    """Tests for NotificationService.send()."""

    @pytest.mark.asyncio
    async def test_successful_send(
        self, notification_service: NotificationService
    ) -> None:
        request = _make_send_request()
        response = await notification_service.send(request)
        assert response.notification is not None
        assert response.notification.status in (
            NotificationStatus.SENT,
            NotificationStatus.QUEUED,
        )

    @pytest.mark.asyncio
    async def test_uses_specified_channel(
        self,
        notification_service: NotificationService,
        mock_email_sender: AsyncMock,
    ) -> None:
        request = _make_send_request(channel=NotificationChannel.EMAIL)
        await notification_service.send(request)
        mock_email_sender.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_idempotency_returns_existing(
        self,
        notification_service: NotificationService,
        mock_delivery_tracker: AsyncMock,
    ) -> None:
        existing_notification = Notification(
            notification_id="existing-123",
            status=NotificationStatus.SENT,
        )
        mock_delivery_tracker.find_by_correlation_id.return_value = [
            existing_notification,
        ]
        request = _make_send_request(correlation_id="corr-123")
        response = await notification_service.send(request)
        assert response.notification.notification_id == "existing-123"

    @pytest.mark.asyncio
    async def test_raises_when_channel_unavailable(
        self,
        notification_service: NotificationService,
        mock_preference_service: AsyncMock,
    ) -> None:
        """Recipient with no address for the channel should raise."""
        request = _make_send_request(
            channel=NotificationChannel.WEBHOOK,
            recipient=Recipient(user_id="user-1", email="user@example.com"),
        )
        with pytest.raises(ChannelUnavailableError):
            await notification_service.send(request)

    @pytest.mark.asyncio
    async def test_delegates_to_optimizer_when_no_channel(
        self,
        notification_service: NotificationService,
        mock_delivery_optimizer: AsyncMock,
    ) -> None:
        request = _make_send_request(channel=None)
        await notification_service.send(request)
        mock_delivery_optimizer.select_channel.assert_called_once()


# ---------------------------------------------------------------------------
# Preference management
# ---------------------------------------------------------------------------

class TestPreferenceManagement:
    """Tests for NotificationService.get_preferences()."""

    @pytest.mark.asyncio
    async def test_returns_user_preferences(
        self, notification_service: NotificationService
    ) -> None:
        from src.domain.ports.inbound.send_notification import (
            GetPreferencesRequest,
        )
        request = GetPreferencesRequest(recipient_id="user-1")
        response = await notification_service.get_preferences(request)
        assert response.preference is not None

    @pytest.mark.asyncio
    async def test_raises_for_missing_recipient(
        self,
        notification_service: NotificationService,
        mock_preference_service: AsyncMock,
    ) -> None:
        from src.domain.ports.inbound.send_notification import (
            GetPreferencesRequest,
        )
        mock_preference_service.get_preference.return_value = None
        request = GetPreferencesRequest(recipient_id="nonexistent")
        with pytest.raises(NotificationNotFoundError):
            await notification_service.get_preferences(request)


# ---------------------------------------------------------------------------
# Delivery optimization
# ---------------------------------------------------------------------------

class TestDeliveryOptimization:
    """Tests for delivery optimization integration."""

    @pytest.mark.asyncio
    async def test_defers_low_priority_when_optimizer_recommends(
        self,
        notification_service: NotificationService,
        mock_delivery_optimizer: AsyncMock,
    ) -> None:
        class DeferredOptimization:
            should_defer = True
            optimal_time = datetime.now(timezone.utc) + timedelta(hours=2)

        mock_delivery_optimizer.optimize_delivery_time.return_value = DeferredOptimization()
        request = _make_send_request(
            priority=NotificationPriority.LOW,
            channel=None,
        )
        response = await notification_service.send(request)
        assert response.scheduled_delivery is not None

    @pytest.mark.asyncio
    async def test_high_priority_bypasses_optimization(
        self,
        notification_service: NotificationService,
        mock_delivery_optimizer: AsyncMock,
    ) -> None:
        request = _make_send_request(
            priority=NotificationPriority.URGENT,
            channel=NotificationChannel.EMAIL,
        )
        await notification_service.send(request)
        mock_delivery_optimizer.optimize_delivery_time.assert_not_called()


from datetime import timedelta
