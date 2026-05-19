"""
Notification Service - ML-driven multi-channel notification delivery.

This service implements the hexagonal architecture pattern with clear separation
between domain logic (zero external dependencies), inbound adapters (gRPC + Kafka
consumers), and outbound adapters (email, SMS, push, webhook channels). The domain
layer uses Protocol-based interfaces for all ports, ensuring testability and
adherence to the Dependency Inversion Principle. All monetary and business logic
remains in the domain layer, while infrastructure concerns are isolated in adapters.
"""

__version__ = "0.1.0"
