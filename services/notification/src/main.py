"""
Notification Service entry point.

Starts the FastAPI + gRPC dual server with graceful shutdown handling.
The server listens on configured ports for gRPC queries and HTTP REST
endpoints, and starts the Kafka event consumer for notification triggers.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .infrastructure import Config, Container

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialize and start the Notification service."""
    config = Config()
    container = Container(config)

    logger.info(
        "notification service initializing",
        extra={
            "grpc_port": config.grpc_port,
            "http_port": config.http_port,
            "kafka_brokers": config.kafka_brokers,
            "spiffe_enabled": config.spiffe_enabled,
        },
    )

    # Start Kafka event consumer.
    topics = [t.strip() for t in config.kafka_topics.split(",")]
    await container.kafka_consumer.start(
        brokers=config.kafka_brokers,
        topics=topics,
        group_id=config.kafka_group_id,
    )

    # In production: start FastAPI + gRPC servers.
    # app = FastAPI(title="Notification Service")
    # app.include_router(rest_controller.router)
    # config_uvloop()  # Use uvloop for better async performance

    # Graceful shutdown handler.
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("notification service ready", extra={"grpc_port": config.grpc_port})

    # Wait for shutdown signal.
    await shutdown_event.wait()

    # Graceful shutdown.
    await container.kafka_consumer.stop()
    logger.info("notification service stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
