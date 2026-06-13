"""
Security tests for WebhookSenderAdapter.

Verifies SSRF protection by testing both safe and restricted URLs.
Mocks DNS resolution to test various IP ranges without actual network calls.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from src.adapters.outbound.channels.webhook_sender import WebhookSenderAdapter
from src.domain.ports.outbound.channel_sender import DeliveryRequest
from src.domain.models.notification import NotificationChannel

@pytest.fixture
def webhook_adapter():
    return WebhookSenderAdapter()

@pytest.fixture
def delivery_request():
    return DeliveryRequest(
        notification_id="test-id",
        recipient_address="http://example.com/webhook",
        subject="Test",
        short_content="Test body",
        channel=NotificationChannel.WEBHOOK,
    )

@pytest.mark.asyncio
async def test_is_safe_url_blocks_loopback(webhook_adapter):
    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        # Mock getaddrinfo to return loopback IP
        mock_loop.getaddrinfo = AsyncMock(return_value=[(None, None, None, None, ("127.0.0.1", 80))])
        mock_get_loop.return_value = mock_loop

        assert await webhook_adapter._is_safe_url("http://127.0.0.1/webhook") is False
        assert await webhook_adapter._is_safe_url("http://localhost/webhook") is False

@pytest.mark.asyncio
async def test_is_safe_url_blocks_private_ip(webhook_adapter):
    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        # Mock getaddrinfo to return private IP
        mock_loop.getaddrinfo = AsyncMock(return_value=[(None, None, None, None, ("192.168.1.1", 80))])
        mock_get_loop.return_value = mock_loop

        assert await webhook_adapter._is_safe_url("http://192.168.1.1/webhook") is False

@pytest.mark.asyncio
async def test_is_safe_url_allows_public_ip(webhook_adapter):
    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        # Mock getaddrinfo to return a public IP (Google DNS)
        mock_loop.getaddrinfo = AsyncMock(return_value=[(None, None, None, None, ("8.8.8.8", 80))])
        mock_get_loop.return_value = mock_loop

        assert await webhook_adapter._is_safe_url("http://google.com/webhook") is True

@pytest.mark.asyncio
async def test_make_request_aborts_on_unsafe_url(webhook_adapter, delivery_request):
    with patch.object(webhook_adapter, "_is_safe_url", return_value=False):
        response = await webhook_adapter._make_request(
            "http://unsafe.com", {}, {}
        )
        assert response.success is False
        assert "SSRF Protection" in response.error_message

@pytest.mark.asyncio
async def test_send_fails_immediately_on_unsafe_url(webhook_adapter):
    unsafe_request = DeliveryRequest(
        notification_id="test-id",
        recipient_address="http://127.0.0.1/webhook",
        subject="Test",
        short_content="Test body",
        channel=NotificationChannel.WEBHOOK,
    )
    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.getaddrinfo = AsyncMock(return_value=[(None, None, None, None, ("127.0.0.1", 80))])
        mock_get_loop.return_value = mock_loop

        response = await webhook_adapter.send(unsafe_request)
        assert response.success is False
        assert "SSRF Protection" in response.error_message
