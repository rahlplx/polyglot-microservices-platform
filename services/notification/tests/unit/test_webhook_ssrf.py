import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from src.adapters.outbound.channels.webhook_sender import WebhookSenderAdapter
from src.domain.ports.outbound.channel_sender import DeliveryRequest
from src.domain.models.notification import NotificationChannel

@pytest.mark.asyncio
async def test_webhook_sender_ssrf_protection_private_ip():
    """
    Test confirming that the WebhookSenderAdapter correctly blocks
    requests to private/loopback IP addresses.
    """
    adapter = WebhookSenderAdapter()

    # Target a local address that should be blocked
    private_url = "http://127.0.0.1:8080/admin"

    request = DeliveryRequest(
        notification_id="test-123",
        channel=NotificationChannel.WEBHOOK,
        recipient_address=private_url,
        subject="Test",
        plain_text_content="Test body",
        correlation_id="corr-123"
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        response = await adapter.send(request)

        # Request should be blocked, so mock_post should NOT be called
        assert not mock_post.called, "SSRF Protection: Request to private IP should be blocked"
        assert response.success is False
        assert "SSRF Protection" in response.error_message

@pytest.mark.asyncio
async def test_webhook_sender_ssrf_protection_metadata_service():
    """
    Test confirming that the WebhookSenderAdapter correctly blocks
    requests to cloud metadata services.
    """
    adapter = WebhookSenderAdapter()

    # Target AWS metadata service
    metadata_url = "http://169.254.169.254/latest/meta-data/"

    request = DeliveryRequest(
        notification_id="test-123",
        channel=NotificationChannel.WEBHOOK,
        recipient_address=metadata_url,
        subject="Test",
        plain_text_content="Test body",
        correlation_id="corr-123"
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        response = await adapter.send(request)

        # Request should be blocked
        assert not mock_post.called, "SSRF Protection: Request to metadata IP should be blocked"
        assert response.success is False
        assert "SSRF Protection" in response.error_message

@pytest.mark.asyncio
async def test_webhook_sender_allows_safe_url():
    """
    Test confirming that the WebhookSenderAdapter still allows
    requests to safe public IP addresses.
    """
    adapter = WebhookSenderAdapter()

    # Target a public address (google.com)
    # We mock getaddrinfo to return a public IP
    safe_url = "https://www.google.com/webhook"

    request = DeliveryRequest(
        notification_id="test-123",
        channel=NotificationChannel.WEBHOOK,
        recipient_address=safe_url,
        subject="Test",
        plain_text_content="Test body",
        correlation_id="corr-123"
    )

    # Mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "Success"

    # Mock getaddrinfo to return a public IP (8.8.8.8)
    with patch("asyncio.get_event_loop") as mock_loop_getter:
        mock_loop = AsyncMock()
        mock_loop_getter.return_value = mock_loop
        # addrinfo format: (family, type, proto, canonname, sockaddr)
        mock_loop.getaddrinfo.return_value = [
            (None, None, None, None, ("8.8.8.8", 443))
        ]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            response = await adapter.send(request)

            assert mock_post.called, "Should allow request to safe public URL"
            assert response.success is True
