"""CDC Relay — Entry Point"""
import asyncio
import logging
from .infrastructure.config import Config
from .adapters.outbound.kafka_connect import KafkaConnectAdapter
from .domain.services import ReplicationService


async def main() -> None:
    config = Config.from_env()
    logging.basicConfig(level=config.log_level)
    log = logging.getLogger("cdc-relay")

    registry = KafkaConnectAdapter(config.kafka_connect_url)
    service = ReplicationService(registry)

    log.info("CDC Relay started — Kafka Connect: %s", config.kafka_connect_url)
    # gRPC server wiring goes here (Phase 2)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
