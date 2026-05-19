"""
Analytics Service entry point.

Starts the FastAPI + gRPC dual server for metric queries and report generation,
alongside the Kafka consumer for real-time event processing.
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
    """Initialize and start the Analytics service."""
    config = Config()
    container = Container(config)

    logger.info(
        "analytics service initializing",
        extra={
            "grpc_port": config.grpc_port,
            "http_port": config.http_port,
            "clickhouse_dsn": config.clickhouse_dsn.replace(config.db_password, "***") if config.db_password else config.clickhouse_dsn,
        },
    )

    # Start Kafka event consumer.
    topics = [t.strip() for t in config.kafka_topics.split(",")]
    await container.kafka_consumer.start(
        brokers=config.kafka_brokers,
        topics=topics,
        group_id=config.kafka_group_id,
    )

    # Graceful shutdown handler.
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("analytics service ready", extra={"grpc_port": config.grpc_port})
    await shutdown_event.wait()

    # Graceful shutdown.
    await container.kafka_consumer.stop()
    logger.info("analytics service stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
