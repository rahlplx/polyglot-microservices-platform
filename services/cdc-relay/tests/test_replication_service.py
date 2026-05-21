"""CDC Relay — ReplicationService unit tests (TDD, mock registry)"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.domain.models import ConnectorState, ConnectorStatus, SnapshotMode, StartReplicationRequest
from src.domain.services import ReplicationService


def make_service():
    registry = AsyncMock()
    return ReplicationService(registry), registry


def req(**kw):
    defaults = dict(source_database="orders_db", source_tables=["public.orders"],
                    target_topic_prefix="platform.orders")
    defaults.update(kw)
    return StartReplicationRequest(**defaults)


@pytest.mark.asyncio
async def test_start_replication_calls_registry():
    svc, reg = make_service()
    reg.create_connector.return_value = ConnectorState("debezium-orders_db-platform-orders", ConnectorStatus.UNASSIGNED)
    state = await svc.start_replication(req())
    reg.create_connector.assert_called_once()
    assert state.connector_name == "debezium-orders_db-platform-orders"


@pytest.mark.asyncio
async def test_start_replication_rejects_invalid():
    svc, _ = make_service()
    with pytest.raises(ValueError, match="source_database"):
        await svc.start_replication(req(source_database=""))


@pytest.mark.asyncio
async def test_stop_replication_deletes_connector():
    svc, reg = make_service()
    state = await svc.stop_replication("debezium-orders_db-platform-orders")
    reg.delete_connector.assert_called_once_with("debezium-orders_db-platform-orders")
    assert state.status == ConnectorStatus.UNASSIGNED


@pytest.mark.asyncio
async def test_stop_replication_rejects_empty_name():
    svc, _ = make_service()
    with pytest.raises(ValueError):
        await svc.stop_replication("")


@pytest.mark.asyncio
async def test_list_connectors_aggregates_status():
    svc, reg = make_service()
    reg.list_connectors.return_value = ["conn-a", "conn-b"]
    reg.get_connector_status.side_effect = [
        ConnectorState("conn-a", ConnectorStatus.RUNNING, tasks_total=1, tasks_running=1),
        ConnectorState("conn-b", ConnectorStatus.FAILED),
    ]
    states = await svc.list_connectors()
    assert len(states) == 2
    assert states[0].is_healthy
    assert not states[1].is_healthy


@pytest.mark.asyncio
async def test_list_connectors_handles_status_error():
    svc, reg = make_service()
    reg.list_connectors.return_value = ["bad-conn"]
    reg.get_connector_status.side_effect = Exception("timeout")
    states = await svc.list_connectors()
    assert states[0].status == ConnectorStatus.FAILED


@pytest.mark.asyncio
async def test_build_config_contains_outbox_transform():
    svc, reg = make_service()
    reg.create_connector.return_value = ConnectorState("x", ConnectorStatus.UNASSIGNED)
    await svc.start_replication(req())
    config = reg.create_connector.call_args[0][0]
    assert config["config"]["transforms"] == "outbox"
    assert "EventRouter" in config["config"]["transforms.outbox.type"]


@pytest.mark.asyncio
async def test_build_config_uses_pgoutput_plugin():
    svc, reg = make_service()
    reg.create_connector.return_value = ConnectorState("x", ConnectorStatus.UNASSIGNED)
    await svc.start_replication(req())
    config = reg.create_connector.call_args[0][0]
    assert config["config"]["plugin.name"] == "pgoutput"


@pytest.mark.asyncio
async def test_snapshot_mode_propagated():
    svc, reg = make_service()
    reg.create_connector.return_value = ConnectorState("x", ConnectorStatus.UNASSIGNED)
    await svc.start_replication(req(snapshot_mode=SnapshotMode.SCHEMA_ONLY))
    config = reg.create_connector.call_args[0][0]
    assert config["config"]["snapshot.mode"] == "schema_only"
