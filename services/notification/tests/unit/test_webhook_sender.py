"""
Unit tests for WebhookSenderAdapter.
Tests SSRF protection and delivery logic.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.adapters.outbound.channels.webhook_sender import WebhookSenderAdapter
from src.domain.ports.outbound.channel_sender import DeliveryRequest
from src.domain.models.notification import NotificationChannel

@pytest.fixture
def webhook_sender():
    return WebhookSenderAdapter()

@pytest.fixture
def delivery_request():
    return DeliveryRequest(
        notification_id="notif-123",
        channel=NotificationChannel.WEBHOOK,
        recipient_address="https://example.com/webhook",
        subject="Test",
        plain_text_content="Hello",
        correlation_id="corr-123"
    )

@pytest.mark.asyncio
async def test_send_successful(webhook_sender, delivery_request):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        response = await webhook_sender.send(delivery_request)

        assert response.success is True
        mock_post.assert_called_once()

@pytest.mark.asyncio
async def test_ssrf_protection_blocks_local_ip(webhook_sender):
    request = DeliveryRequest(
        notification_id="notif-123",
        channel=NotificationChannel.WEBHOOK,
        recipient_address="http://127.0.0.1/webhook",
        subject="Test",
        plain_text_content="Hello"
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        # Before fix, this will fail with TypeError in comparison or success=True if mocked correctly
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        response = await webhook_sender.send(request)

        assert response.success is False
        assert any(word in response.error_message.lower() for word in ["ssrf", "private", "local", "forbidden"])
        mock_post.assert_not_called()

@pytest.mark.asyncio
async def test_ssrf_protection_blocks_private_range(webhook_sender):
    request = DeliveryRequest(
        notification_id="notif-123",
        channel=NotificationChannel.WEBHOOK,
        recipient_address="http://192.168.1.1/webhook",
        subject="Test",
        plain_text_content="Hello"
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        response = await webhook_sender.send(request)

        assert response.success is False
        assert "private" in response.error_message.lower()
        mock_post.assert_not_called()

@pytest.mark.asyncio
async def test_ssrf_protection_blocks_metadata_service(webhook_sender):
    request = DeliveryRequest(
        notification_id="notif-123",
        channel=NotificationChannel.WEBHOOK,
        recipient_address="http://169.254.169.254/latest/meta-data/",
        subject="Test",
        plain_text_content="Hello"
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        response = await webhook_sender.send(request)

        assert response.success is False
        assert any(word in response.error_message.lower() for word in ["private", "reserved", "metadata"])
        mock_post.assert_not_called()
