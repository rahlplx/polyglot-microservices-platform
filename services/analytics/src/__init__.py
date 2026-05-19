"""
Analytics Service - Data pipeline orchestration, OTel trace processing, and business metrics.

This service implements the hexagonal architecture pattern for the analytics
subsystem of the gstack platform. It consumes business events and OTel spans
via Kafka, aggregates metrics into time-series data stored in ClickHouse,
and serves query results via gRPC and REST APIs. The domain layer has zero
external dependencies, with all infrastructure concerns isolated in adapters.
"""

__version__ = "0.1.0"
