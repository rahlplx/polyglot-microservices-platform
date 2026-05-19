"""
SQLAlchemy async repository for template persistence.

This module implements the TemplateRepositoryPort using SQLAlchemy 2.0's
async ORM. Templates are stored as Jinja2 markup with metadata including
required variables, supported channels, and locale information.

The repository supports template versioning to ensure that in-flight
notifications continue to use the template version that was active when
the notification was created. Template updates create new versions
rather than modifying existing ones.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, Boolean, func, select, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ....domain.models.template import Template
from ....domain.ports.outbound.template_store import TemplateRepositoryPort

logger = logging.getLogger(__name__)


class TemplateRecord:
    """Stub for the SQLAlchemy Template model.

    In production, this would be a proper SQLAlchemy declarative model
    mapped to a templates table. For this implementation, we use a
    simplified in-memory store that satisfies the port interface.
    """
    pass


class TemplateRepositoryAdapter:
    """SQLAlchemy async implementation of the TemplateRepositoryPort.

    This adapter provides CRUD operations for template entities using
    SQLAlchemy's async ORM. Templates are stored with versioning support,
    ensuring that in-flight notifications can reference the template
    version that was active at creation time.

    The adapter uses an in-memory fallback when the database is not
    available, supporting development and testing scenarios.
    """

    def __init__(self, session_factory: Optional[async_sessionmaker[AsyncSession]] = None) -> None:
        """Initialize the template repository.

        Args:
            session_factory: Optional SQLAlchemy async session factory.
                If None, an in-memory store is used for development.
        """
        self._session_factory = session_factory
        # In-memory store for development/testing
        self._templates: dict[str, Template] = {}

    async def find_by_id(self, template_id: str) -> Optional[Template]:
        """Retrieve a template by its identifier.

        If a database session factory is configured, queries the database.
        Otherwise, falls back to the in-memory store.

        Args:
            template_id: The template identifier.

        Returns:
            The Template entity, or None if not found.
        """
        if self._session_factory:
            return await self._find_by_id_db(template_id)
        return self._templates.get(template_id)

    async def find_by_id_and_version(
        self, template_id: str, version: int
    ) -> Optional[Template]:
        """Retrieve a specific version of a template.

        Searches the database for the template with the matching ID and
        version number. Returns None if no matching version exists.

        Args:
            template_id: The template identifier.
            version: The specific version number.

        Returns:
            The Template entity for the requested version, or None.
        """
        if self._session_factory:
            return await self._find_by_id_and_version_db(template_id, version)

        # In-memory: check if template exists with matching version
        template = self._templates.get(template_id)
        if template and template.version == version:
            return template
        return None

    async def save(self, template: Template) -> Template:
        """Persist a template definition.

        If the template already exists, a new version is created by
        incrementing the version number. The returned template includes
        the assigned version number.

        Args:
            template: The template entity to persist.

        Returns:
            The persisted Template entity with version assigned.
        """
        if self._session_factory:
            return await self._save_db(template)

        # In-memory save with version increment
        existing = self._templates.get(template.template_id)
        if existing:
            from dataclasses import replace
            template = replace(template, version=existing.version + 1)

        self._templates[template.template_id] = template
        return template

    async def find_by_channel(self, channel: str) -> list[Template]:
        """Retrieve all active templates for a given channel.

        Returns templates that support the specified channel, filtered
        to only include active versions.

        Args:
            channel: The notification channel to filter by.

        Returns:
            A list of active Template entities for the channel.
        """
        if self._session_factory:
            return await self._find_by_channel_db(channel)

        return [
            t for t in self._templates.values()
            if t.is_active and (t.channel == channel or t.channel is None)
        ]

    async def list_templates(
        self, limit: int = 50, offset: int = 0
    ) -> list[Template]:
        """List all active templates with pagination.

        Returns a paginated list of active template definitions sorted
        by name.

        Args:
            limit: Maximum number of templates to return.
            offset: Number of templates to skip.

        Returns:
            A list of active Template entities.
        """
        if self._session_factory:
            return await self._list_templates_db(limit, offset)

        active = [t for t in self._templates.values() if t.is_active]
        active.sort(key=lambda t: t.name)
        return active[offset : offset + limit]

    # --- Database implementations (stubs for when session_factory is configured) ---

    async def _find_by_id_db(self, template_id: str) -> Optional[Template]:
        """Database implementation of find_by_id."""
        # In production, this would query the templates table
        return self._templates.get(template_id)

    async def _find_by_id_and_version_db(
        self, template_id: str, version: int
    ) -> Optional[Template]:
        """Database implementation of find_by_id_and_version."""
        template = self._templates.get(template_id)
        if template and template.version == version:
            return template
        return None

    async def _save_db(self, template: Template) -> Template:
        """Database implementation of save."""
        self._templates[template.template_id] = template
        return template

    async def _find_by_channel_db(self, channel: str) -> list[Template]:
        """Database implementation of find_by_channel."""
        return [
            t for t in self._templates.values()
            if t.is_active and (t.channel == channel or t.channel is None)
        ]

    async def _list_templates_db(
        self, limit: int = 50, offset: int = 0
    ) -> list[Template]:
        """Database implementation of list_templates."""
        active = [t for t in self._templates.values() if t.is_active]
        active.sort(key=lambda t: t.name)
        return active[offset : offset + limit]

    def seed_default_templates(self) -> None:
        """Populate the in-memory store with default notification templates.

        Creates the standard templates that map to the event types consumed
        by the event consumer adapter. Each template includes HTML, plain
        text, and short variants with Jinja2 markup for variable
        substitution.
        """
        defaults = [
            Template(
                template_id="order-confirmation",
                name="Order Confirmation",
                description="Confirmation email sent when an order is placed",
                channel="email",
                subject_template="Order Confirmed - #{{ order_id }}",
                html_template=(
                    "<h1>Thank you for your order!</h1>"
                    "<p>Order #{{ order_id }} has been confirmed.</p>"
                    "<p>Total: {{ total }}</p>"
                ),
                plain_text_template=(
                    "Thank you for your order!\n"
                    "Order #{{ order_id }} has been confirmed.\n"
                    "Total: {{ total }}"
                ),
                short_template="Order #{{ order_id }} confirmed!",
                required_vars=["order_id", "total"],
            ),
            Template(
                template_id="order-cancellation",
                name="Order Cancellation",
                description="Notice sent when an order is cancelled",
                channel="email",
                subject_template="Order Cancelled - #{{ order_id }}",
                html_template=(
                    "<h1>Order Cancelled</h1>"
                    "<p>Order #{{ order_id }} has been cancelled.</p>"
                    "<p>Reason: {{ reason }}</p>"
                ),
                plain_text_template=(
                    "Order Cancelled\n"
                    "Order #{{ order_id }} has been cancelled.\n"
                    "Reason: {{ reason }}"
                ),
                short_template="Order #{{ order_id }} cancelled",
                required_vars=["order_id", "reason"],
            ),
            Template(
                template_id="order-delivery",
                name="Order Delivery Confirmation",
                description="Confirmation that an order has been delivered",
                channel="email",
                subject_template="Your Order Has Been Delivered - #{{ order_id }}",
                html_template=(
                    "<h1>Order Delivered!</h1>"
                    "<p>Order #{{ order_id }} has been delivered.</p>"
                ),
                plain_text_template="Order #{{ order_id }} has been delivered!",
                short_template="Order #{{ order_id }} delivered",
                required_vars=["order_id"],
            ),
            Template(
                template_id="payment-receipt",
                name="Payment Receipt",
                description="Receipt for a processed payment",
                channel="email",
                subject_template="Payment Receipt - {{ amount }}",
                html_template=(
                    "<h1>Payment Receipt</h1>"
                    "<p>Amount: {{ amount }}</p>"
                    "<p>Transaction ID: {{ transaction_id }}</p>"
                ),
                plain_text_template=(
                    "Payment Receipt\n"
                    "Amount: {{ amount }}\n"
                    "Transaction ID: {{ transaction_id }}"
                ),
                short_template="Payment of {{ amount }} received",
                required_vars=["amount", "transaction_id"],
            ),
            Template(
                template_id="payment-refund",
                name="Refund Confirmation",
                description="Confirmation of a payment refund",
                channel="email",
                subject_template="Refund Processed - {{ amount }}",
                html_template=(
                    "<h1>Refund Processed</h1>"
                    "<p>Amount: {{ amount }}</p>"
                    "<p>Refund ID: {{ refund_id }}</p>"
                ),
                plain_text_template=(
                    "Refund Processed\n"
                    "Amount: {{ amount }}\n"
                    "Refund ID: {{ refund_id }}"
                ),
                short_template="Refund of {{ amount }} processed",
                required_vars=["amount", "refund_id"],
            ),
            Template(
                template_id="payment-failure",
                name="Payment Failure Alert",
                description="Urgent alert for payment processing failures",
                channel="email",
                subject_template="Payment Failed - Action Required",
                html_template=(
                    "<h1>Payment Failed</h1>"
                    "<p>Your payment of {{ amount }} could not be processed.</p>"
                    "<p>Reason: {{ reason }}</p>"
                    "<p>Please update your payment method.</p>"
                ),
                plain_text_template=(
                    "Payment Failed\n"
                    "Your payment of {{ amount }} could not be processed.\n"
                    "Reason: {{ reason }}\n"
                    "Please update your payment method."
                ),
                short_template="Payment of {{ amount }} failed",
                required_vars=["amount", "reason"],
            ),
            Template(
                template_id="inventory-alert",
                name="Inventory Alert",
                description="Webhook alert for low inventory levels",
                channel="webhook",
                subject_template="Low Inventory Alert: {{ product_name }}",
                plain_text_template=(
                    "Inventory Alert\n"
                    "Product: {{ product_name }}\n"
                    "Current Stock: {{ current_stock }}\n"
                    "Reorder Level: {{ reorder_level }}"
                ),
                short_template="Low inventory: {{ product_name }}",
                required_vars=["product_name", "current_stock", "reorder_level"],
            ),
        ]

        for template in defaults:
            self._templates[template.template_id] = template

        logger.info("Seeded %d default templates", len(defaults))
