"""
Event storage port for the Analytics service.

This module defines the EventRepository protocol, which is the outbound port
for storing and retrieving raw domain events that have been ingested from the
Kafka event backbone. Events are stored in PostgreSQL as JSON documents with
metadata columns for efficient querying. The event store serves as the source
of truth for reprocessing and audit trails, complementing the time series
store which holds the derived metric data.

The event store also manages dashboard configurations, report templates,
and alert rules as specialized event types. This design allows the analytics
service to reconstruct its entire configuration from the event history,
supporting disaster recovery and configuration versioning.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventRepository(Protocol):
    """Outbound port for raw event storage and retrieval.

    This protocol defines the contract for persisting domain events that
    have been consumed from Kafka and transformed into analytics records.
    The repository supports both insertion of new events and retrieval for
    reprocessing or audit purposes. Events are stored with full fidelity
    to enable re-derivation of metrics when aggregation logic changes.
    """

    def store_event(self, event: dict[str, Any]) -> None:
        """Persist a single domain event to the event store.

        Events are stored with their full CloudEvents envelope, including
        the event ID, type, source, timestamp, and data payload. The event
        ID is used for idempotency: duplicate events with the same ID are
        silently ignored to support exactly-once processing semantics.

        Args:
            event: A dictionary containing the CloudEvents envelope and
                data payload. Must include 'id', 'type', 'source', and
                'time' fields at minimum.

        Raises:
            EventStorageError: If the event cannot be persisted.
        """
        ...

    def store_events_batch(self, events: list[dict[str, Any]]) -> int:
        """Persist a batch of domain events to the event store.

        Batch insertion is significantly more efficient than individual
        inserts for high-throughput ingestion pipelines. The method
        returns the count of actually inserted events, excluding duplicates
        that were already present.

        Args:
            events: A list of event dictionaries to persist.

        Returns:
            The number of events that were newly inserted (excluding duplicates).

        Raises:
            EventStorageError: If the batch write operation fails.
        """
        ...

    def get_events(
        self,
        event_type: str | None = None,
        source: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve events matching the specified filters.

        Supports filtering by event type, source service, and time range.
        Used primarily for reprocessing scenarios where the aggregation
        logic has changed and metrics need to be recomputed from the
        original event data.

        Args:
            event_type: Optional CloudEvents type filter.
            source: Optional source service filter.
            start_time: Optional start of the time range filter.
            end_time: Optional end of the time range filter.
            limit: Maximum number of events to return.

        Returns:
            A list of event dictionaries matching the filters.
        """
        ...

    def get_dashboard_config(self, dashboard_id: str) -> dict[str, Any] | None:
        """Retrieve a dashboard configuration by its ID.

        Dashboard configurations are stored as JSON documents in PostgreSQL.
        The configuration specifies the panels, queries, visualization types,
        and display options for a dashboard.

        Args:
            dashboard_id: The unique identifier of the dashboard.

        Returns:
            The dashboard configuration dictionary, or None if not found.
        """
        ...

    def list_dashboard_configs(self, tag: str | None = None) -> list[dict[str, Any]]:
        """List all available dashboard configurations.

        Supports optional filtering by tag for categorized dashboard
        navigation.

        Args:
            tag: Optional tag filter for dashboards.

        Returns:
            A list of dashboard configuration summaries.
        """
        ...

    def save_dashboard_config(self, dashboard_id: str, config: dict[str, Any]) -> None:
        """Save or update a dashboard configuration.

        Upserts the dashboard configuration, creating a new record if the
        ID does not exist or updating the existing record if it does.

        Args:
            dashboard_id: The unique identifier of the dashboard.
            config: The dashboard configuration dictionary.

        Raises:
            DashboardConfigError: If the configuration is invalid.
        """
        ...
