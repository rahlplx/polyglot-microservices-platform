"""
Unit tests for SSRF protection in WebhookSenderAdapter.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from src.adapters.outbound.channels.webhook_sender import WebhookSenderAdapter
from src.domain.ports.outbound.channel_sender import DeliveryRequest
from src.domain.models.notification import NotificationChannel


@pytest.fixture
def webhook_sender() -> WebhookSenderAdapter:
    return WebhookSenderAdapter()


def _make_delivery_request(url: str) -> DeliveryRequest:
    return DeliveryRequest(
        notification_id="ntf-123",
        recipient_address=url,
        channel=NotificationChannel.WEBHOOK,
        subject="Test",
        plain_text_content="Test",
        correlation_id="corr-123",
    )


@pytest.mark.asyncio
async def test_blocks_loopback_ip(webhook_sender: WebhookSenderAdapter) -> None:
    request = _make_delivery_request("http://127.0.0.1/webhook")
    response = await webhook_sender.send(request)
    assert response.success is False
    assert "SSRF Protection" in response.error_message


@pytest.mark.asyncio
async def test_blocks_private_ip(webhook_sender: WebhookSenderAdapter) -> None:
    request = _make_delivery_request("http://192.168.1.1/webhook")
    response = await webhook_sender.send(request)
    assert response.success is False
    assert "SSRF Protection" in response.error_message


@pytest.mark.asyncio
async def test_blocks_localhost(webhook_sender: WebhookSenderAdapter) -> None:
    request = _make_delivery_request("http://localhost/webhook")
    response = await webhook_sender.send(request)
    assert response.success is False
    assert "SSRF Protection" in response.error_message


@pytest.mark.asyncio
async def test_allows_public_domain(webhook_sender: WebhookSenderAdapter) -> None:
    # Use a real domain that should resolve to a public IP
    request = _make_delivery_request("https://example.com/webhook")

    with patch.object(webhook_sender, "_make_request", new_callable=AsyncMock) as mock_make_request:
        mock_make_request.return_value.success = True
        response = await webhook_sender.send(request)

        assert mock_make_request.called
        assert response.success is True


@pytest.mark.asyncio
async def test_blocks_invalid_schemes(webhook_sender: WebhookSenderAdapter) -> None:
    request = _make_delivery_request("ftp://example.com/webhook")
    response = await webhook_sender.send(request)
    assert response.success is False
    assert "SSRF Protection" in response.error_message
