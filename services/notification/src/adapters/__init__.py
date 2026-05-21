"""
Adapters layer for the Notification service.

Adapters implement the port interfaces defined in the domain layer, providing
concrete implementations for infrastructure concerns such as Kafka event
consumption, gRPC query handling, database persistence, external delivery
provider communication, and observability instrumentation.

Adapters are divided into inbound (driving) and outbound (driven) categories.
Inbound adapters receive external requests and invoke domain services through
inbound ports. Outbound adapters implement outbound ports to interact with
external systems on behalf of the domain.
"""
