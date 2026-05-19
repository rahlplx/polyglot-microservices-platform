"""
RL Engine Service entry point.

Starts the gRPC + REST server for policy management, training job
submission, and inference serving. The RL Engine runs as a standalone
service that other services (Notification, Analytics) call for
ML-optimized decision making.
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
    """Initialize and start the RL Engine service."""
    config = Config()
    container = Container(config)

    logger.info(
        "rl engine service initializing",
        extra={
            "grpc_port": config.grpc_port,
            "http_port": config.http_port,
        },
    )

    # Pre-create default policies for each environment.
    from .domain.models import EnvironmentType, PolicyType
    for env in EnvironmentType:
        await container.policy_service.create_policy(
            name=f"default-{env.value.lower()}",
            environment=env,
            policy_type=PolicyType.EPSILON_GREEDY,
        )

    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("rl engine service ready", extra={"grpc_port": config.grpc_port})
    await shutdown_event.wait()
    logger.info("rl engine service stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
