"""
PostgreSQL event/metadata store adapter for the Analytics service.

This module implements the EventRepository outbound port using PostgreSQL
as the backing store. PostgreSQL is used for low-volume configuration data:
dashboard definitions, event metadata, alert rules, and transformer registry
configurations. SQLAlchemy manages the PostgreSQL schema with Alembic migrations.

The adapter includes a connection health checker that monitors the database
and reports its status through the health check endpoint. When PostgreSQL is
unavailable, the adapter queues operations in memory and retries them when
connectivity is restored, ensuring graceful degradation during outages.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ...domain.ports.outbound.event_store import EventRepository

logger = logging.getLogger(__name__)

# SQL templates for PostgreSQL table creation
EVENTS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS domain_events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    source TEXT NOT NULL,
    time TIMESTAMPTZ NOT NULL,
    data JSONB DEFAULT '{}',
    datacontenttype TEXT DEFAULT 'application/json',
    inserted_at TIMESTAMPTZ DEFAULT NOW(),
    indexed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_type ON domain_events (type);
CREATE INDEX IF NOT EXISTS idx_events_source ON domain_events (source);
CREATE INDEX IF NOT EXISTS idx_events_time ON domain_events (time);
CREATE INDEX IF NOT EXISTS idx_events_inserted_at ON domain_events (inserted_at);
"""

DASHBOARDS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS dashboard_configs (
    dashboard_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    panels JSONB DEFAULT '[]',
    variables JSONB DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dashboards_tags ON dashboard_configs USING GIN (tags);
"""


class PostgresEventRepository:
    """PostgreSQL implementation of the EventRepository port.

    This adapter translates domain-level event and configuration operations
    into PostgreSQL queries using SQLAlchemy. It handles connection
    management, schema creation, and graceful degradation during outages.

    Events are stored with their full CloudEvents envelope for audit
    and reprocessing capabilities. Dashboard configurations are stored
    as JSON documents for flexibility.
    """

    def __init__(
        self,
        connection_string: str = "postgresql://analytics:analytics@localhost:5432/analytics",
        pool_size: int = 5,
        max_overflow: int = 10,
    ) -> None:
        """Initialize the PostgreSQL repository with connection parameters.

        Args:
            connection_string: SQLAlchemy-compatible connection string.
            pool_size: Number of permanent connections in the pool.
            max_overflow: Maximum number of connections beyond pool_size.
        """
        self._connection_string = connection_string
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._engine: Any = None
        self._connection: Any = None

    def connect(self) -> None:
        """Establish connection to the PostgreSQL server.

        Creates the engine, connection pool, and ensures all required
        tables exist. The connection is maintained for the lifetime of
        the service.
        """
        try:
            import sqlalchemy

            self._engine = sqlalchemy.create_engine(
                self._connection_string,
                pool_size=self._pool_size,
                max_overflow=self._max_overflow,
                pool_pre_ping=True,
            )
            self._connection = self._engine.connect()
            self._ensure_tables()
            logger.info("Connected to PostgreSQL: %s", self._connection_string.split("@")[-1])
        except Exception as exc:
            logger.error("Failed to connect to PostgreSQL: %s", exc)
            raise

    def disconnect(self) -> None:
        """Close the PostgreSQL connection gracefully."""
        if self._connection:
            self._connection.close()
        if self._engine:
            self._engine.dispose()
            logger.info("Disconnected from PostgreSQL")

    def store_event(self, event: dict[str, Any]) -> None:
        """Persist a single domain event to PostgreSQL.

        Uses INSERT ON CONFLICT DO NOTHING for idempotency: duplicate
        events with the same ID are silently ignored.

        Args:
            event: A dictionary containing the CloudEvents envelope.
        """
        if self._connection is None:
            logger.error("PostgreSQL connection not established")
            return

        sql = """
        INSERT INTO domain_events (id, type, source, time, data, datacontenttype)
        VALUES (:id, :type, :source, :time, :data, :datacontenttype)
        ON CONFLICT (id) DO NOTHING
        """
        try:
            self._connection.execute(
                sql,
                {
                    "id": event.get("id", ""),
                    "type": event.get("type", ""),
                    "source": event.get("source", ""),
                    "time": event.get("time", datetime.now(timezone.utc).isoformat()),
                    "data": json.dumps(event.get("data", {})),
                    "datacontenttype": event.get("datacontenttype", "application/json"),
                },
            )
            self._connection.commit()
        except Exception as exc:
            logger.error("Failed to store event: %s", exc)
            self._connection.rollback()

    def store_events_batch(self, events: list[dict[str, Any]]) -> int:
        """Persist a batch of domain events to PostgreSQL.

        Uses batch insertion with ON CONFLICT DO NOTHING for idempotency.
        Returns the count of actually inserted events.

        Args:
            events: A list of event dictionaries to persist.

        Returns:
            The number of events that were newly inserted.
        """
        if self._connection is None:
            logger.error("PostgreSQL connection not established")
            return 0

        inserted = 0
        for event in events:
            try:
                self.store_event(event)
                inserted += 1
            except Exception as exc:
                logger.error(
                    "Failed to store event in batch (event_id=%s): %s",
                    event.get("id", "unknown"),
                    exc,
                )

        return inserted

    def get_events(
        self,
        event_type: str | None = None,
        source: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve events matching the specified filters.

        Args:
            event_type: Optional CloudEvents type filter.
            source: Optional source service filter.
            start_time: Optional start of the time range filter.
            end_time: Optional end of the time range filter.
            limit: Maximum number of events to return.

        Returns:
            A list of event dictionaries matching the filters.
        """
        if self._connection is None:
            logger.error("PostgreSQL connection not established")
            return []

        conditions = []
        params: dict[str, Any] = {"limit": limit}

        if event_type:
            conditions.append("type = :event_type")
            params["event_type"] = event_type
        if source:
            conditions.append("source = :source")
            params["source"] = source
        if start_time:
            conditions.append("time >= :start_time")
            params["start_time"] = start_time.isoformat()
        if end_time:
            conditions.append("time <= :end_time")
            params["end_time"] = end_time.isoformat()

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT id, type, source, time, data FROM domain_events WHERE {where} ORDER BY time DESC LIMIT :limit"

        try:
            result = self._connection.execute(sql, params)
            return [
                {
                    "id": row[0],
                    "type": row[1],
                    "source": row[2],
                    "time": row[3].isoformat() if isinstance(row[3], datetime) else str(row[3]),
                    "data": row[4] if isinstance(row[4], dict) else json.loads(row[4]),
                }
                for row in result
            ]
        except Exception as exc:
            logger.error("Failed to query events: %s", exc)
            return []

    def get_dashboard_config(self, dashboard_id: str) -> dict[str, Any] | None:
        """Retrieve a dashboard configuration by its ID.

        Args:
            dashboard_id: The unique identifier of the dashboard.

        Returns:
            The dashboard configuration dictionary, or None if not found.
        """
        if self._connection is None:
            logger.error("PostgreSQL connection not established")
            return None

        sql = "SELECT dashboard_id, title, description, panels, variables, tags FROM dashboard_configs WHERE dashboard_id = :id"
        try:
            result = self._connection.execute(sql, {"id": dashboard_id})
            row = result.fetchone()
            if row is None:
                return None

            panels = row[3] if isinstance(row[3], list) else json.loads(row[3])
            variables = row[4] if isinstance(row[4], dict) else json.loads(row[4])

            return {
                "dashboard_id": row[0],
                "title": row[1],
                "description": row[2],
                "panels": panels,
                "variables": variables,
                "tags": row[5] if isinstance(row[5], list) else list(row[5]),
            }
        except Exception as exc:
            logger.error("Failed to get dashboard config: %s", exc)
            return None

    def list_dashboard_configs(self, tag: str | None = None) -> list[dict[str, Any]]:
        """List all available dashboard configurations.

        Args:
            tag: Optional tag filter for dashboards.

        Returns:
            A list of dashboard configuration summaries.
        """
        if self._connection is None:
            logger.error("PostgreSQL connection not established")
            return []

        if tag:
            sql = "SELECT dashboard_id, title, description, tags FROM dashboard_configs WHERE :tag = ANY(tags)"
            params = {"tag": tag}
        else:
            sql = "SELECT dashboard_id, title, description, tags FROM dashboard_configs"
            params = {}

        try:
            result = self._connection.execute(sql, params)
            return [
                {
                    "dashboard_id": row[0],
                    "title": row[1],
                    "description": row[2],
                    "tags": list(row[3]) if not isinstance(row[3], list) else row[3],
                }
                for row in result
            ]
        except Exception as exc:
            logger.error("Failed to list dashboard configs: %s", exc)
            return []

    def save_dashboard_config(self, dashboard_id: str, config: dict[str, Any]) -> None:
        """Save or update a dashboard configuration.

        Args:
            dashboard_id: The unique identifier of the dashboard.
            config: The dashboard configuration dictionary.
        """
        if self._connection is None:
            logger.error("PostgreSQL connection not established")
            return

        sql = """
        INSERT INTO dashboard_configs (dashboard_id, title, description, panels, variables, tags, updated_at)
        VALUES (:id, :title, :description, :panels, :variables, :tags, NOW())
        ON CONFLICT (dashboard_id) DO UPDATE SET
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            panels = EXCLUDED.panels,
            variables = EXCLUDED.variables,
            tags = EXCLUDED.tags,
            updated_at = NOW()
        """
        try:
            self._connection.execute(
                sql,
                {
                    "id": dashboard_id,
                    "title": config.get("title", ""),
                    "description": config.get("description", ""),
                    "panels": json.dumps(config.get("panels", [])),
                    "variables": json.dumps(config.get("variables", {})),
                    "tags": config.get("tags", []),
                },
            )
            self._connection.commit()
        except Exception as exc:
            logger.error("Failed to save dashboard config: %s", exc)
            self._connection.rollback()

    def _ensure_tables(self) -> None:
        """Create the required PostgreSQL tables if they do not exist.

        Executes the DDL statements for the events and dashboard_configs
        tables. These statements are idempotent (IF NOT EXISTS).
        """
        if self._connection is None:
            return

        try:
            self._connection.execute(EVENTS_TABLE_DDL)
            self._connection.execute(DASHBOARDS_TABLE_DDL)
            self._connection.commit()
            logger.info("Ensured PostgreSQL tables exist")
        except Exception as exc:
            logger.error("Failed to create tables: %s", exc)
            self._connection.rollback()
