"""
Persistence outbound adapters for the Analytics service.

This package contains the database adapter implementations for both
ClickHouse (time-series data) and PostgreSQL (metadata and event storage).
Each adapter implements the corresponding domain outbound port, translating
domain-level operations into database-specific queries and commands.
"""

from .clickhouse_repo import ClickHouseTimeSeriesRepository
from .postgres_repo import PostgresEventRepository

__all__ = [
    "ClickHouseTimeSeriesRepository",
    "PostgresEventRepository",
]
