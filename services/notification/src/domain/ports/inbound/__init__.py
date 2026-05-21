"""
Inbound ports (driving ports) for the Notification service.

Inbound ports define the use case interfaces through which external actors
interact with the notification domain. These are the entry points for all
notification operations: sending notifications, querying delivery status,
and managing preferences. Each port method encapsulates a complete business
transaction with well-defined input/output types and error conditions.
"""

from .send_notification import SendNotificationPort, GetDeliveryStatusPort, GetPreferencesPort

__all__ = [
    "SendNotificationPort",
    "GetDeliveryStatusPort",
    "GetPreferencesPort",
]
