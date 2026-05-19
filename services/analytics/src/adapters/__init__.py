"""
Adapters layer for the Analytics service.

Adapters are the concrete implementations of the domain ports. Inbound
adapters handle incoming requests from external callers (gRPC, REST, Kafka
events), while outbound adapters handle outgoing interactions with
infrastructure (databases, message brokers, observability systems). Each
adapter is independently replaceable without modifying the domain layer.
"""
