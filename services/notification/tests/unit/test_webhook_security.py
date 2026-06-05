"""
Security unit tests for Webhook SSRF protection.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
import socket
from dataclasses import replace

from src.adapters.outbound.channels.webhook_sender import WebhookSenderAdapter
from src.domain.ports.outbound.channel_sender import DeliveryRequest
from src.domain.models.notification import NotificationChannel


@pytest.fixture
def webhook_sender() -> WebhookSenderAdapter:
    return WebhookSenderAdapter()


@pytest.fixture
def delivery_request() -> DeliveryRequest:
    return DeliveryRequest(
        notification_id="notif-123",
        channel=NotificationChannel.WEBHOOK,
        recipient_address="https://safe-external-site.com/webhook",
        subject="Test",
        plain_text_content="Test body",
        correlation_id="corr-123",
    )


@pytest.mark.asyncio
async def test_safe_url_allowed(
    webhook_sender: WebhookSenderAdapter,
    delivery_request: DeliveryRequest,
) -> None:
    # Mock hostname resolution to a public IP
    with patch("socket.getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ]

        # Mock the actual HTTP request to avoid network calls
        with patch.object(webhook_sender, "_make_request", new_callable=AsyncMock) as mock_make_request:
            mock_make_request.return_value = AsyncMock(success=True)

            response = await webhook_sender.send(delivery_request)

            assert response.success is True
            mock_make_request.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe_url, resolved_ip", [
    ("http://localhost/webhook", "127.0.0.1"),
    ("http://127.0.0.1/webhook", "127.0.0.1"),
    ("http://10.0.0.1/webhook", "10.0.0.1"),
    ("http://192.168.1.1/webhook", "192.168.1.1"),
    ("http://172.16.0.1/webhook", "172.16.0.1"),
    ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
    ("http://internal-service.local/webhook", "10.0.0.5"),
])
async def test_unsafe_urls_blocked(
    webhook_sender: WebhookSenderAdapter,
    delivery_request: DeliveryRequest,
    unsafe_url: str,
    resolved_ip: str,
) -> None:
    req = replace(delivery_request, recipient_address=unsafe_url)

    # Mock hostname resolution to an unsafe IP
    with patch("socket.getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved_ip, 0))
        ]

        # Ensure _make_request is NEVER called for unsafe URLs
        with patch.object(webhook_sender, "_make_request", new_callable=AsyncMock) as mock_make_request:
            response = await webhook_sender.send(req)

            assert response.success is False
            assert "SSRF Protection" in response.error_message
            mock_make_request.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_scheme_blocked(
    webhook_sender: WebhookSenderAdapter,
    delivery_request: DeliveryRequest,
) -> None:
    req = replace(delivery_request, recipient_address="file:///etc/passwd")

    with patch.object(webhook_sender, "_make_request", new_callable=AsyncMock) as mock_make_request:
        response = await webhook_sender.send(req)

        assert response.success is False
        assert "SSRF Protection" in response.error_message
        mock_make_request.assert_not_called()
