"""CDC Relay — Domain Models"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


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


@dataclass(frozen=True)
class PipelineConfig:
    column_include_list: List[str] = field(default_factory=list)
    column_exclude_list: List[str] = field(default_factory=list)
    max_batch_size: int = 2048
    max_queue_size: int = 8192
    heartbeat_interval_ms: int = 10_000

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.column_include_list and self.column_exclude_list:
            errors.append("column_include_list and column_exclude_list are mutually exclusive")
        if self.max_batch_size <= 0:
            errors.append("max_batch_size must be positive")
        if self.max_queue_size < self.max_batch_size:
            errors.append(f"max_queue_size ({self.max_queue_size}) must be >= max_batch_size ({self.max_batch_size})")
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
        errors.extend(self.pipeline_config.validate())
        return errors

    def connector_name(self) -> str:
        safe = self.target_topic_prefix.replace(".", "-").replace("/", "-")
        db = self.source_database.replace("/", "-").replace(":", "-")
        return f"debezium-{db}-{safe}"


@dataclass
class ConnectorState:
    connector_name: str
    status: ConnectorStatus
    tasks_total: int = 0
    tasks_running: int = 0
    error_message: Optional[str] = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_healthy(self) -> bool:
        return self.status == ConnectorStatus.RUNNING and self.tasks_running == self.tasks_total > 0


@dataclass
class SourceOffset:
    lsn: int
    txid: Optional[int] = None
    timestamp: Optional[datetime] = None


@dataclass
class ReplicationStatus:
    connector_name: str
    source_database: str
    status: ConnectorStatus
    offset: Optional[SourceOffset] = None
    lag_ms: int = 0
    events_captured: int = 0
    events_filtered: int = 0
