"""CDC Relay — Replication Domain Service"""
from __future__ import annotations
from typing import List
from .models import ConnectorState, ConnectorStatus, ReplicationStatus, StartReplicationRequest
from .ports import ConnectorRegistryPort, ReplicationPort


class ReplicationService(ReplicationPort):
    def __init__(self, registry: ConnectorRegistryPort) -> None:
        self._registry = registry

    async def start_replication(self, request: StartReplicationRequest) -> ConnectorState:
        errors = request.validate()
        if errors:
            raise ValueError("Invalid request: " + "; ".join(errors))
        return await self._registry.create_connector(self._build_config(request))

    async def stop_replication(self, connector_name: str) -> ConnectorState:
        if not connector_name:
            raise ValueError("connector_name is required")
        await self._registry.delete_connector(connector_name)
        return ConnectorState(connector_name=connector_name, status=ConnectorStatus.UNASSIGNED)

    async def get_replication_status(self, connector_name: str) -> ReplicationStatus:
        state = await self._registry.get_connector_status(connector_name)
        db = connector_name.replace("debezium-", "").split("-")[0]
        return ReplicationStatus(connector_name=connector_name, source_database=db, status=state.status)

    async def list_connectors(self) -> List[ConnectorState]:
        names = await self._registry.list_connectors()
        states = []
        for name in names:
            try:
                states.append(await self._registry.get_connector_status(name))
            except Exception:
                states.append(ConnectorState(name, ConnectorStatus.FAILED))
        return states

    def _build_config(self, req: StartReplicationRequest) -> dict:
        cfg = req.pipeline_config
        config = {
            "name": req.connector_name(),
            "config": {
                "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
                "database.hostname": "${env:POSTGRES_HOST}",
                "database.port": "5432",
                "database.user": "${env:POSTGRES_USER}",
                "database.password": "${env:POSTGRES_PASSWORD}",
                "database.dbname": req.source_database,
                "database.server.name": req.connector_name(),
                "table.include.list": ",".join(req.source_tables),
                "topic.prefix": req.target_topic_prefix,
                "snapshot.mode": req.snapshot_mode.value.lower(),
                "plugin.name": "pgoutput",
                "publication.autocreate.mode": "filtered",
                "slot.name": "debezium_" + req.connector_name().replace("-", "_"),
                "max.batch.size": str(cfg.max_batch_size),
                "max.queue.size": str(cfg.max_queue_size),
                "heartbeat.interval.ms": str(cfg.heartbeat_interval_ms),
                "transforms": "outbox",
                "transforms.outbox.type": "io.debezium.transforms.outbox.EventRouter",
                "transforms.outbox.table.field.event.id": "event_id",
                "transforms.outbox.table.field.event.type": "event_type",
                "transforms.outbox.table.field.event.payload": "payload",
                "value.converter": "org.apache.kafka.connect.json.JsonConverter",
                "value.converter.schemas.enable": "false",
                "key.converter": "org.apache.kafka.connect.storage.StringConverter",
            },
        }
        if cfg.column_include_list:
            config["config"]["column.include.list"] = ",".join(cfg.column_include_list)
        if cfg.column_exclude_list:
            config["config"]["column.exclude.list"] = ",".join(cfg.column_exclude_list)
        return config
