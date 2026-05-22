"""
TDD Unit Tests — CDC Relay Domain Logic.

Tests the core Debezium connector configuration and replication pipeline
validation logic. These tests define the expected behaviour BEFORE
implementation, driving the CDC relay service build.

All tests use pure Python — zero infrastructure dependencies.
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Domain models (inline for TDD — will move to src/ when implemented)
# ---------------------------------------------------------------------------

class SnapshotMode(str, Enum):
    INITIAL = "INITIAL"
    SCHEMA_ONLY = "SCHEMA_ONLY"
    NEVER = "NEVER"
    WHEN_NEEDED = "WHEN_NEEDED"


class ConnectorStatus(str, Enum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    UNASSIGNED = "UNASSIGNED"


class PauseReason(str, Enum):
    MAINTENANCE_WINDOW = "MAINTENANCE_WINDOW"
    SCHEMA_MIGRATION = "SCHEMA_MIGRATION"
    UPSTREAM_ISSUE = "UPSTREAM_ISSUE"
    MANUAL_PAUSE = "MANUAL_PAUSE"


@dataclass(frozen=True)
class PipelineConfig:
    """Debezium connector tuning parameters."""
    column_include_list: List[str] = field(default_factory=list)
    column_exclude_list: List[str] = field(default_factory=list)
    max_batch_size: int = 2048
    max_queue_size: int = 8192
    heartbeat_interval_ms: int = 10_000

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.column_include_list and self.column_exclude_list:
            errors.append(
                "column_include_list and column_exclude_list are mutually exclusive"
            )
        if self.max_batch_size <= 0:
            errors.append("max_batch_size must be positive")
        if self.max_queue_size < self.max_batch_size:
            errors.append(
                f"max_queue_size ({self.max_queue_size}) must be >= max_batch_size ({self.max_batch_size})"
            )
        if self.heartbeat_interval_ms < 0:
            errors.append("heartbeat_interval_ms must be non-negative")
        return errors


@dataclass(frozen=True)
class StartReplicationRequest:
    source_database: str
    source_tables: List[str]
    target_topic_prefix: str
    snapshot_mode: SnapshotMode = SnapshotMode.INITIAL
    pipeline_config: PipelineConfig = field(default_factory=PipelineConfig)

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.source_database:
            errors.append("source_database is required")
        if not self.source_tables:
            errors.append("source_tables must contain at least one table")
        if not self.target_topic_prefix:
            errors.append("target_topic_prefix is required")
        if "." in self.target_topic_prefix and self.target_topic_prefix.count(".") > 2:
            errors.append("target_topic_prefix must have at most 2 dot separators")
        errors.extend(self.pipeline_config.validate())
        return errors

    def connector_name(self) -> str:
        """Derive a deterministic connector name from source + prefix."""
        safe_prefix = self.target_topic_prefix.replace(".", "-").replace("/", "-")
        safe_db = self.source_database.replace("/", "-").replace(":", "-")
        return f"debezium-{safe_db}-{safe_prefix}"


@dataclass
class SourceOffset:
    lsn: int
    txid: Optional[int] = None
    timestamp: Optional[datetime] = None


@dataclass
class ConnectorMetrics:
    events_captured: int = 0
    events_filtered: int = 0
    throughput_eps: float = 0.0
    lag_ms: int = 0


# ---------------------------------------------------------------------------
# Tests: PipelineConfig validation
# ---------------------------------------------------------------------------

class TestPipelineConfigValidation:
    def test_valid_default_config(self) -> None:
        cfg = PipelineConfig()
        assert cfg.validate() == []

    def test_include_and_exclude_mutually_exclusive(self) -> None:
        cfg = PipelineConfig(
            column_include_list=["orders.id"],
            column_exclude_list=["orders.internal_note"],
        )
        errors = cfg.validate()
        assert any("mutually exclusive" in e for e in errors)

    def test_include_only_is_valid(self) -> None:
        cfg = PipelineConfig(column_include_list=["orders.id", "orders.status"])
        assert cfg.validate() == []

    def test_exclude_only_is_valid(self) -> None:
        cfg = PipelineConfig(column_exclude_list=["orders.internal_note"])
        assert cfg.validate() == []

    def test_max_batch_size_must_be_positive(self) -> None:
        cfg = PipelineConfig(max_batch_size=0)
        errors = cfg.validate()
        assert any("max_batch_size" in e for e in errors)

    def test_max_queue_must_be_gte_batch(self) -> None:
        cfg = PipelineConfig(max_batch_size=4096, max_queue_size=2048)
        errors = cfg.validate()
        assert any("max_queue_size" in e for e in errors)

    def test_heartbeat_cannot_be_negative(self) -> None:
        cfg = PipelineConfig(heartbeat_interval_ms=-1)
        errors = cfg.validate()
        assert any("heartbeat_interval_ms" in e for e in errors)

    def test_zero_heartbeat_is_valid(self) -> None:
        """heartbeat_interval_ms=0 disables heartbeats (valid Debezium config)."""
        cfg = PipelineConfig(heartbeat_interval_ms=0)
        assert cfg.validate() == []


# ---------------------------------------------------------------------------
# Tests: StartReplicationRequest validation
# ---------------------------------------------------------------------------

class TestStartReplicationRequestValidation:
    def _valid_request(self, **overrides) -> StartReplicationRequest:
        defaults = dict(
            source_database="orders_db",
            source_tables=["public.orders", "public.order_lines"],
            target_topic_prefix="platform.orders",
            snapshot_mode=SnapshotMode.INITIAL,
        )
        defaults.update(overrides)
        return StartReplicationRequest(**defaults)

    def test_valid_request_passes(self) -> None:
        req = self._valid_request()
        assert req.validate() == []

    def test_empty_source_database_fails(self) -> None:
        req = self._valid_request(source_database="")
        assert any("source_database" in e for e in req.validate())

    def test_empty_source_tables_fails(self) -> None:
        req = self._valid_request(source_tables=[])
        assert any("source_tables" in e for e in req.validate())

    def test_empty_topic_prefix_fails(self) -> None:
        req = self._valid_request(target_topic_prefix="")
        assert any("target_topic_prefix" in e for e in req.validate())

    def test_over_dotted_topic_prefix_fails(self) -> None:
        req = self._valid_request(target_topic_prefix="a.b.c.d")
        assert any("dot" in e for e in req.validate())

    def test_two_dot_prefix_is_valid(self) -> None:
        req = self._valid_request(target_topic_prefix="platform.orders.v1")
        assert req.validate() == []

    def test_pipeline_config_errors_bubble_up(self) -> None:
        bad_cfg = PipelineConfig(max_batch_size=0)
        req = self._valid_request(pipeline_config=bad_cfg)
        errors = req.validate()
        assert any("max_batch_size" in e for e in errors)

    def test_all_snapshot_modes_are_valid(self) -> None:
        for mode in SnapshotMode:
            req = self._valid_request(snapshot_mode=mode)
            assert req.validate() == [], f"Mode {mode} should be valid"


# ---------------------------------------------------------------------------
# Tests: Connector name derivation
# ---------------------------------------------------------------------------

class TestConnectorNameDerivation:
    def test_deterministic(self) -> None:
        req = StartReplicationRequest(
            source_database="orders_db",
            source_tables=["public.orders"],
            target_topic_prefix="platform.orders",
        )
        assert req.connector_name() == req.connector_name()

    def test_dots_replaced_with_dashes(self) -> None:
        req = StartReplicationRequest(
            source_database="orders_db",
            source_tables=["public.orders"],
            target_topic_prefix="platform.orders",
        )
        name = req.connector_name()
        assert "." not in name

    def test_unique_per_database_prefix_combination(self) -> None:
        req_a = StartReplicationRequest(
            source_database="db_a",
            source_tables=["t"],
            target_topic_prefix="prefix.a",
        )
        req_b = StartReplicationRequest(
            source_database="db_b",
            source_tables=["t"],
            target_topic_prefix="prefix.a",
        )
        assert req_a.connector_name() != req_b.connector_name()

    def test_starts_with_debezium(self) -> None:
        req = StartReplicationRequest(
            source_database="orders_db",
            source_tables=["public.orders"],
            target_topic_prefix="platform",
        )
        assert req.connector_name().startswith("debezium-")


# ---------------------------------------------------------------------------
# Tests: SourceOffset
# ---------------------------------------------------------------------------

class TestSourceOffset:
    def test_lsn_only_is_sufficient(self) -> None:
        offset = SourceOffset(lsn=12345678)
        assert offset.lsn == 12345678
        assert offset.txid is None
        assert offset.timestamp is None

    def test_full_offset(self) -> None:
        ts = datetime.now(timezone.utc)
        offset = SourceOffset(lsn=999, txid=42, timestamp=ts)
        assert offset.txid == 42
        assert offset.timestamp == ts

    def test_lsn_ordering(self) -> None:
        o1 = SourceOffset(lsn=100)
        o2 = SourceOffset(lsn=200)
        assert o2.lsn > o1.lsn


# ---------------------------------------------------------------------------
# Tests: ConnectorMetrics
# ---------------------------------------------------------------------------

class TestConnectorMetrics:
    def test_defaults_are_zero(self) -> None:
        m = ConnectorMetrics()
        assert m.events_captured == 0
        assert m.events_filtered == 0
        assert m.throughput_eps == 0.0
        assert m.lag_ms == 0

    def test_event_capture_ratio(self) -> None:
        m = ConnectorMetrics(events_captured=1000, events_filtered=50)
        pass_through_ratio = (m.events_captured - m.events_filtered) / m.events_captured
        assert pass_through_ratio == pytest.approx(0.95)

    def test_lagging_connector_detection(self) -> None:
        LAG_THRESHOLD_MS = 30_000
        ok_metrics = ConnectorMetrics(lag_ms=1000)
        lagging_metrics = ConnectorMetrics(lag_ms=60_000)
        assert ok_metrics.lag_ms < LAG_THRESHOLD_MS
        assert lagging_metrics.lag_ms > LAG_THRESHOLD_MS
