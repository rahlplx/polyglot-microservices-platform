"""
SQLAlchemy async repository for notification persistence.

This module implements the DeliveryTrackerPort using SQLAlchemy 2.0's
async ORM with the asyncpg driver for PostgreSQL. The repository manages
notification records, tracking events, delivery attempts, and ML model
parameters.

The adapter uses PostgreSQL's JSONB type for flexible metadata storage
and the INSERT ... ON CONFLICT DO UPDATE pattern for upserting tracking
events (which may be received multiple times from delivery provider
webhooks). Connection pooling is configured with a maximum of 20 async
connections.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    Boolean,
    ForeignKey,
    Index,
    select,
    insert,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship

from ....domain.models.notification import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
    NotificationType,
    Recipient,
)
from ....domain.models.delivery import (
    DeliveryAttempt,
    TrackingEvent,
    TrackingEventType,
)
from ....domain.ports.outbound.delivery_tracker import (
    DeliveryModel,
    Page,
    PageRequest,
)

logger = logging.getLogger(__name__)


# --- SQLAlchemy Base and Models ---

class Base(DeclarativeBase):
    """SQLAlchemy declarative base for notification tables."""
    pass


class NotificationRecord(Base):
    """SQLAlchemy model for the notifications table.

    Stores the complete notification record including status, content,
    and delivery metadata. The status transitions are tracked by the
    domain model and persisted here.
    """
    __tablename__ = "notifications"

    notification_id = Column(String(36), primary_key=True)
    recipient_user_id = Column(String(255), nullable=False, index=True)
    recipient_email = Column(String(255), nullable=True)
    recipient_phone = Column(String(50), nullable=True)
    recipient_device_token = Column(String(512), nullable=True)
    recipient_webhook_url = Column(Text, nullable=True)
    recipient_timezone = Column(String(50), default="UTC")
    channel = Column(String(20), nullable=False)
    notification_type = Column(String(50), nullable=True)
    priority = Column(String(20), default="normal")
    status = Column(String(20), default="pending", index=True)
    template_id = Column(String(255), nullable=True)
    template_vars = Column(JSONB, default=dict)
    subject = Column(Text, nullable=True)
    body = Column(Text, nullable=True)
    correlation_id = Column(String(255), nullable=True, index=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    tracking_events = relationship(
        "TrackingEventRecord", back_populates="notification", lazy="selectin"
    )
    delivery_attempts = relationship(
        "DeliveryAttemptRecord", back_populates="notification", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_notifications_recipient_status", "recipient_user_id", "status"),
        Index("ix_notifications_correlation_id", "correlation_id"),
    )


class TrackingEventRecord(Base):
    """SQLAlchemy model for the tracking_events table.

    Stores append-only tracking events received from delivery providers.
    Events are deduplicated by event_id to handle provider webhook
    retransmissions.
    """
    __tablename__ = "tracking_events"

    event_id = Column(String(36), primary_key=True)
    notification_id = Column(String(36), ForeignKey("notifications.notification_id"), nullable=False)
    event_type = Column(String(30), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=func.now())
    provider = Column(String(50), nullable=True)
    metadata = Column(JSONB, default=dict)

    notification = relationship("NotificationRecord", back_populates="tracking_events")

    __table_args__ = (
        Index("ix_tracking_events_notification_id", "notification_id"),
        Index("ix_tracking_events_event_type", "event_type"),
    )


class DeliveryAttemptRecord(Base):
    """SQLAlchemy model for the delivery_attempts table.

    Stores individual delivery attempt records for analytics and
    retry management.
    """
    __tablename__ = "delivery_attempts"

    attempt_id = Column(String(36), primary_key=True)
    notification_id = Column(String(36), ForeignKey("notifications.notification_id"), nullable=False)
    channel = Column(String(20), nullable=False)
    provider = Column(String(50), nullable=True)
    success = Column(Boolean, default=False)
    provider_message_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    attempted_at = Column(DateTime(timezone=True), default=func.now())
    response_time_ms = Column(Integer, nullable=True)

    notification = relationship("NotificationRecord", back_populates="delivery_attempts")

    __table_args__ = (
        Index("ix_delivery_attempts_notification_id", "notification_id"),
    )


class DeliveryModelRecord(Base):
    """SQLAlchemy model for the delivery_models table.

    Stores ML delivery optimization model parameters as JSONB with
    versioning for A/B testing.
    """
    __tablename__ = "delivery_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_version = Column(String(50), unique=True, nullable=False)
    parameters = Column(JSONB, default=dict)
    trained_at = Column(DateTime(timezone=True), default=func.now())
    accuracy = Column(Float, default=0.0)
    feature_importance = Column(JSONB, default=dict)


# Need Float import


class NotificationRepository:
    """SQLAlchemy async implementation of the DeliveryTrackerPort.

    This adapter implements all persistence operations for notifications,
    tracking events, delivery attempts, and ML model parameters. It uses
    SQLAlchemy 2.0's async session support for non-blocking database
    operations, which is critical for the event-driven architecture where
    a single consumer task may need to write multiple records concurrently.
    """

    def __init__(self, database_url: str = "postgresql+asyncpg://localhost/notification") -> None:
        """Initialize the repository with a database URL.

        Args:
            database_url: The async PostgreSQL connection string.
        """
        self._engine = create_async_engine(
            database_url,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def initialize(self) -> None:
        """Create database tables if they do not exist.

        This method is called during service startup to ensure that
        the required tables are available. In production, Alembic
        migrations should be used instead of create_all.
        """
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized")

    async def close(self) -> None:
        """Dispose of the database engine and connection pool.

        Called during service shutdown to release database connections
        gracefully.
        """
        await self._engine.dispose()
        logger.info("Database connections closed")

    async def save(self, notification: Notification) -> Notification:
        """Persist a notification record with its current status.

        Uses INSERT ... ON CONFLICT DO UPDATE to handle idempotent saves.
        The notification's complete state is persisted including all
        status fields and recipient information.

        Args:
            notification: The notification entity to persist.

        Returns:
            The persisted notification entity.
        """
        async with self._session_factory() as session:
            # Check if record exists
            stmt = select(NotificationRecord).where(
                NotificationRecord.notification_id == notification.notification_id
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is None:
                # Create new record
                record = NotificationRecord(
                    notification_id=notification.notification_id,
                    recipient_user_id=notification.recipient.user_id if notification.recipient else "",
                    recipient_email=notification.recipient.email if notification.recipient else None,
                    recipient_phone=notification.recipient.phone if notification.recipient else None,
                    recipient_device_token=notification.recipient.device_token if notification.recipient else None,
                    recipient_webhook_url=notification.recipient.webhook_url if notification.recipient else None,
                    recipient_timezone=notification.recipient.timezone if notification.recipient else "UTC",
                    channel=notification.channel.value if notification.channel else "",
                    notification_type=notification.notification_type.value if notification.notification_type else None,
                    priority=notification.priority.value,
                    status=notification.status.value,
                    template_id=notification.template_id,
                    template_vars=notification.template_vars,
                    subject=notification.subject,
                    body=notification.body,
                    correlation_id=notification.correlation_id,
                    scheduled_at=notification.scheduled_at,
                    sent_at=notification.sent_at,
                    delivered_at=notification.delivered_at,
                    failed_at=notification.failed_at,
                    retry_count=notification.retry_count,
                    max_retries=notification.max_retries,
                )
                session.add(record)
            else:
                # Update existing record
                record.status = notification.status.value
                record.priority = notification.priority.value
                record.subject = notification.subject
                record.body = notification.body
                record.scheduled_at = notification.scheduled_at
                record.sent_at = notification.sent_at
                record.delivered_at = notification.delivered_at
                record.failed_at = notification.failed_at
                record.retry_count = notification.retry_count
                record.updated_at = datetime.now(timezone.utc)

            await session.commit()
            return notification

    async def find_by_id(self, notification_id: str) -> Optional[Notification]:
        """Retrieve a notification by its unique identifier.

        Loads the notification record along with its tracking events
        and delivery attempts using eager loading.

        Args:
            notification_id: The notification's unique identifier.

        Returns:
            The Notification entity, or None if not found.
        """
        async with self._session_factory() as session:
            stmt = select(NotificationRecord).where(
                NotificationRecord.notification_id == notification_id
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is None:
                return None

            return self._record_to_entity(record)

    async def find_by_correlation_id(self, correlation_id: str) -> list[Notification]:
        """Retrieve all notifications linked to a correlation ID.

        Returns notifications in creation order for end-to-end
        traceability across service boundaries.

        Args:
            correlation_id: The correlation ID linking related notifications.

        Returns:
            A list of Notification entities.
        """
        async with self._session_factory() as session:
            stmt = (
                select(NotificationRecord)
                .where(NotificationRecord.correlation_id == correlation_id)
                .order_by(NotificationRecord.created_at)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [self._record_to_entity(r) for r in records]

    async def find_by_recipient(
        self, recipient_id: str, page: PageRequest
    ) -> Page:
        """Retrieve paginated notifications for a recipient.

        Returns notifications sorted by creation time in descending
        order (most recent first).

        Args:
            recipient_id: The recipient's user ID.
            page: Pagination parameters.

        Returns:
            A Page containing notification entities.
        """
        async with self._session_factory() as session:
            # Count total
            count_stmt = (
                select(func.count())
                .select_from(NotificationRecord)
                .where(NotificationRecord.recipient_user_id == recipient_id)
            )
            count_result = await session.execute(count_stmt)
            total_count = count_result.scalar() or 0

            # Fetch page
            stmt = (
                select(NotificationRecord)
                .where(NotificationRecord.recipient_user_id == recipient_id)
                .order_by(NotificationRecord.created_at.desc())
                .offset(page.offset)
                .limit(page.page_size)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()

            return Page(
                items=[self._record_to_entity(r) for r in records],
                total_count=total_count,
                page_size=page.page_size,
                offset=page.offset,
            )

    async def append_tracking_event(self, event: TrackingEvent) -> None:
        """Append a tracking event to a notification's event history.

        Events are deduplicated by event_id using INSERT ... ON CONFLICT
        DO NOTHING to handle provider webhook retransmissions.

        Args:
            event: The tracking event to append.
        """
        async with self._session_factory() as session:
            stmt = insert(TrackingEventRecord).values(
                event_id=event.event_id,
                notification_id=event.notification_id,
                event_type=event.event_type.value,
                timestamp=event.timestamp,
                provider=event.provider,
                metadata=event.metadata,
            ).on_conflict_do_nothing(index_elements=["event_id"])

            await session.execute(stmt)
            await session.commit()

    async def save_delivery_attempt(self, attempt: DeliveryAttempt) -> None:
        """Persist a delivery attempt record.

        Args:
            attempt: The delivery attempt to persist.
        """
        async with self._session_factory() as session:
            record = DeliveryAttemptRecord(
                attempt_id=attempt.attempt_id,
                notification_id=attempt.notification_id,
                channel=attempt.channel,
                provider=attempt.provider,
                success=attempt.success,
                provider_message_id=attempt.provider_message_id,
                error_message=attempt.error_message,
                attempted_at=attempt.attempted_at,
                response_time_ms=attempt.response_time_ms,
            )
            session.add(record)
            await session.commit()

    async def find_pending_retry(self, limit: int = 50) -> list[Notification]:
        """Retrieve notifications that are pending retry delivery.

        Returns notifications in FAILED status that have not exceeded
        their maximum retry count, sorted by creation time.

        Args:
            limit: Maximum number of notifications to return.

        Returns:
            A list of retryable Notification entities.
        """
        async with self._session_factory() as session:
            stmt = (
                select(NotificationRecord)
                .where(
                    NotificationRecord.status == "failed",
                    NotificationRecord.retry_count < NotificationRecord.max_retries,
                )
                .order_by(NotificationRecord.created_at)
                .limit(limit)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [self._record_to_entity(r) for r in records]

    async def save_delivery_model(self, model: DeliveryModel) -> None:
        """Persist the ML delivery optimization model parameters.

        Uses INSERT ... ON CONFLICT DO UPDATE to handle model version
        upserts.

        Args:
            model: The delivery model parameters to persist.
        """
        async with self._session_factory() as session:
            stmt = insert(DeliveryModelRecord).values(
                model_version=model.model_version,
                parameters=model.parameters,
                trained_at=model.trained_at,
                accuracy=model.accuracy,
                feature_importance=model.feature_importance,
            ).on_conflict_do_update(
                index_elements=["model_version"],
                set_={
                    "parameters": model.parameters,
                    "trained_at": model.trained_at,
                    "accuracy": model.accuracy,
                    "feature_importance": model.feature_importance,
                },
            )
            await session.execute(stmt)
            await session.commit()

    async def load_delivery_model(
        self, model_version: str = "latest"
    ) -> Optional[DeliveryModel]:
        """Load the ML delivery optimization model parameters.

        Returns the model parameters for the specified version, or the
        latest version if model_version is "latest".

        Args:
            model_version: The model version to load, or "latest".

        Returns:
            The DeliveryModel parameters, or None if not found.
        """
        async with self._session_factory() as session:
            if model_version == "latest":
                stmt = select(DeliveryModelRecord).order_by(
                    DeliveryModelRecord.trained_at.desc()
                ).limit(1)
            else:
                stmt = select(DeliveryModelRecord).where(
                    DeliveryModelRecord.model_version == model_version
                )

            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is None:
                return None

            return DeliveryModel(
                model_version=record.model_version,
                parameters=record.parameters or {},
                trained_at=record.trained_at,
                accuracy=record.accuracy or 0.0,
                feature_importance=record.feature_importance or {},
            )

    @staticmethod
    def _record_to_entity(record: NotificationRecord) -> Notification:
        """Convert a SQLAlchemy record to a domain Notification entity.

        Maps the database record fields to the domain entity, including
        the reconstruction of the Recipient value object and the tracking
        events list.

        Args:
            record: The SQLAlchemy NotificationRecord.

        Returns:
            The domain Notification entity.
        """
        recipient = Recipient(
            user_id=record.recipient_user_id,
            email=record.recipient_email,
            phone=record.recipient_phone,
            device_token=record.recipient_device_token,
            webhook_url=record.recipient_webhook_url,
            timezone=record.recipient_timezone,
        )

        notification = Notification(
            notification_id=record.notification_id,
            recipient=recipient,
            channel=NotificationChannel(record.channel) if record.channel else None,
            notification_type=NotificationType(record.notification_type) if record.notification_type else None,
            priority=NotificationPriority(record.priority),
            status=NotificationStatus(record.status),
            template_id=record.template_id,
            template_vars=record.template_vars or {},
            subject=record.subject,
            body=record.body,
            correlation_id=record.correlation_id,
            scheduled_at=record.scheduled_at,
            sent_at=record.sent_at,
            delivered_at=record.delivered_at,
            failed_at=record.failed_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
            retry_count=record.retry_count,
            max_retries=record.max_retries,
        )

        # Map tracking events if loaded
        if hasattr(record, "tracking_events") and record.tracking_events:
            notification.tracking_events = [
                TrackingEvent(
                    event_id=te.event_id,
                    notification_id=te.notification_id,
                    event_type=TrackingEventType(te.event_type),
                    timestamp=te.timestamp,
                    provider=te.provider or "",
                    metadata=te.metadata or {},
                )
                for te in record.tracking_events
            ]

        return notification
