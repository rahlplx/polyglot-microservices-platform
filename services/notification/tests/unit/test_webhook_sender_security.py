"""
Security tests for WebhookSenderAdapter to verify SSRF protection.
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

@pytest.fixture
def sample_request() -> DeliveryRequest:
    return DeliveryRequest(
        notification_id="notif-123",
        recipient_address="http://example.com/webhook",
        channel=NotificationChannel.WEBHOOK,
        subject="Test",
        short_content="Test body",
    )

@pytest.mark.asyncio
async def test_webhook_sender_allows_public_url(webhook_sender, sample_request):
    """Verify that a normal public URL is still allowed."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = AsyncMock(status_code=200, text="OK")

        response = await webhook_sender.send(sample_request)

        assert response.success is True
        mock_post.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin",
    "http://localhost/config",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.1/internal",
    "http://192.168.1.1/",
    "http://172.16.0.1/",
    "http://0.0.0.0/",
    "file:///etc/passwd",
])
async def test_webhook_sender_blocks_private_ips(webhook_sender, url):
    """
    Verify that private IPs and non-http schemes are blocked.
    In the initial (vulnerable) state, this test might FAIL if it expects blocking
    but the code currently allows it.
    """
    request = DeliveryRequest(
        notification_id="notif-123",
        recipient_address=url,
        channel=NotificationChannel.WEBHOOK,
        subject="Test",
        short_content="Test body",
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = AsyncMock(status_code=200, text="OK")

        response = await webhook_sender.send(request)

        # If vulnerable, response.success might be True or it might fail for other reasons
        # But for reproduction, we want to see if mock_post was called.
        if response.success:
             print(f"VULNERABILITY CONFIRMED: Webhook allowed for {url}")

        # We expect it to be blocked (response.success=False and mock_post NOT called)
        # after we fix it. For now, we expect it to FAIL if it's vulnerable.
        assert response.success is False, f"URL {url} should be blocked"
        assert any(term in response.error_message for term in ["SSRF", "Invalid", "blocked", "private"])
        mock_post.assert_not_called()
