"""
Outbound ports (driven ports) for the Notification service.

Outbound ports define the infrastructure interfaces that the domain depends on.
These are implemented by adapters in the outer layers, providing concrete
implementations for database access, message publishing, delivery provider
communication, and observability. The domain layer only depends on these
port interfaces, never on concrete adapter implementations.
"""

from .channel_sender import ChannelSenderPort, DeliveryRequest, DeliveryResponse
from .template_store import TemplateRepositoryPort
from .preference_store import PreferenceRepositoryPort
from .delivery_tracker import DeliveryTrackerPort

__all__ = [
    "ChannelSenderPort",
    "DeliveryRequest",
    "DeliveryResponse",
    "TemplateRepositoryPort",
    "PreferenceRepositoryPort",
    "DeliveryTrackerPort",
]
