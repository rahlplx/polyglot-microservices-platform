
import pytest
import asyncio
import socket
from unittest.mock import AsyncMock, patch, MagicMock
from src.adapters.outbound.channels.webhook_sender import WebhookSenderAdapter
from src.domain.ports.outbound.channel_sender import DeliveryRequest, DeliveryResponse
from src.domain.models.notification import NotificationChannel

@pytest.mark.asyncio
async def test_webhook_sender_blocks_private_ip():
    adapter = WebhookSenderAdapter(max_retries=0)

    # Mock getaddrinfo to return a private IP
    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        mock_loop.getaddrinfo = AsyncMock(return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 80))
        ])

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            url = "http://internal.service/webhook"
            request = DeliveryRequest(
                notification_id="test-id",
                channel=NotificationChannel.WEBHOOK,
                recipient_address=url,
                subject="Test",
                short_content="Test content"
            )

            response = await adapter.send(request)

            assert not response.success
            assert "SSRF" in response.error_message
            mock_post.assert_not_called()

@pytest.mark.asyncio
async def test_webhook_sender_allows_public_ip():
    adapter = WebhookSenderAdapter(max_retries=0)

    # Mock getaddrinfo to return a public IP
    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        mock_loop.getaddrinfo = AsyncMock(return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))
        ])

        # Mock httpx response
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp

            url = "http://google.com/webhook"
            request = DeliveryRequest(
                notification_id="test-id",
                channel=NotificationChannel.WEBHOOK,
                recipient_address=url,
                subject="Test",
                short_content="Test content"
            )

            response = await adapter.send(request)

            assert response.success
            mock_post.assert_called_once()

@pytest.mark.asyncio
async def test_webhook_sender_blocks_loopback():
    adapter = WebhookSenderAdapter(max_retries=0)

    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        mock_loop.getaddrinfo = AsyncMock(return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ])

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            url = "http://localhost/webhook"
            request = DeliveryRequest(
                notification_id="test-id",
                channel=NotificationChannel.WEBHOOK,
                recipient_address=url,
                subject="Test",
                short_content="Test content"
            )

            response = await adapter.send(request)

            assert not response.success
            assert "SSRF" in response.error_message
            mock_post.assert_not_called()
