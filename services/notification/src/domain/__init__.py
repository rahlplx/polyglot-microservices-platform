"""
Domain layer for the Notification service.

The domain layer contains the core business logic, entity definitions, port
interfaces, and domain services. This layer has ZERO external dependencies --
it depends only on the Python standard library and typing module. All
infrastructure interactions are mediated through port interfaces (Protocols),
which are implemented by adapters in the outer layers.

This separation ensures that the business rules for notification delivery,
template rendering, preference management, and delivery optimization can be
tested in complete isolation from databases, message brokers, and external APIs.
"""
