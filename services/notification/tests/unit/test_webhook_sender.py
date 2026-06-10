import pytest
from unittest.mock import patch, AsyncMock
from src.adapters.outbound.channels.webhook_sender import WebhookSenderAdapter
from src.domain.ports.outbound.channel_sender import DeliveryRequest
from src.domain.models.notification import NotificationChannel

@pytest.fixture
def webhook_adapter():
    return WebhookSenderAdapter()

@pytest.mark.asyncio
async def test_is_safe_url_allows_public_url(webhook_adapter):
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = AsyncMock()
        mock_loop.return_value.getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 80)) # example.com
        ]
        assert await webhook_adapter._is_safe_url("http://example.com") is True

@pytest.mark.asyncio
async def test_is_safe_url_blocks_localhost(webhook_adapter):
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = AsyncMock()
        mock_loop.return_value.getaddrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 80))
        ]
        assert await webhook_adapter._is_safe_url("http://localhost") is False

@pytest.mark.asyncio
async def test_is_safe_url_blocks_private_ip(webhook_adapter):
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = AsyncMock()
        mock_loop.return_value.getaddrinfo.return_value = [
            (2, 1, 6, "", ("192.168.1.1", 80))
        ]
        assert await webhook_adapter._is_safe_url("http://192.168.1.1") is False

@pytest.mark.asyncio
async def test_is_safe_url_blocks_metadata_endpoint(webhook_adapter):
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = AsyncMock()
        mock_loop.return_value.getaddrinfo.return_value = [
            (2, 1, 6, "", ("169.254.169.254", 80))
        ]
        assert await webhook_adapter._is_safe_url("http://169.254.169.254/latest/meta-data/") is False

@pytest.mark.asyncio
async def test_send_blocks_unsafe_url(webhook_adapter):
    request = DeliveryRequest(
        notification_id="test-123",
        channel=NotificationChannel.WEBHOOK,
        recipient_address="http://127.0.0.1/admin",
        subject="Test",
        short_content="Hello"
    )

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = AsyncMock()
        mock_loop.return_value.getaddrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 80))
        ]

        response = await webhook_adapter.send(request)
        assert response.success is False
        assert "SSRF protection" in response.error_message

@pytest.mark.asyncio
async def test_is_safe_url_handles_multiple_ips_blocking_if_any_unsafe(webhook_adapter):
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = AsyncMock()
        mock_loop.return_value.getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 80)),
            (2, 1, 6, "", ("127.0.0.1", 80))
        ]
        assert await webhook_adapter._is_safe_url("http://mixed-records.com") is False
