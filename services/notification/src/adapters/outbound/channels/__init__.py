"""
Channel sender adapters for multi-channel notification delivery.

Each channel adapter implements the ChannelSenderPort interface and handles
the specifics of delivering notifications through a particular channel:
email (SMTP/SES), SMS (Twilio/SNS), push (FCM/APNs), and webhooks (HTTP).

All external provider communication should route through an ACL sidecar
for circuit breaking, rate limiting, and vendor SDK isolation.
"""

from .email_sender import EmailSenderAdapter
from .sms_sender import SmsSenderAdapter
from .push_sender import PushSenderAdapter
from .webhook_sender import WebhookSenderAdapter

__all__ = [
    "EmailSenderAdapter",
    "SmsSenderAdapter",
    "PushSenderAdapter",
    "WebhookSenderAdapter",
]
