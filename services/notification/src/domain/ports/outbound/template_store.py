"""
Template repository port for template persistence.

This module defines the outbound port that the template service uses to
load and store notification templates. Templates are stored in PostgreSQL
with Jinja2 markup and metadata including required variables, supported
channels, and locale information.

The port supports template versioning to ensure that in-flight notifications
continue to use the template version that was active when the notification
was created. This prevents rendering errors due to concurrent template
modifications.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from ...models.template import Template


@runtime_checkable
class TemplateRepositoryPort(Protocol):
    """Outbound port for notification template persistence.

    This port provides CRUD operations for template entities. The template
    service uses this port to load templates for rendering and to manage
    template definitions. Implementations must handle versioning correctly,
    ensuring that the active version is returned by default while allowing
    specific versions to be retrieved for in-flight notification rendering.
    """

    async def find_by_id(self, template_id: str) -> Optional[Template]:
        """Retrieve a template by its identifier.

        Returns the active version of the template, or None if no template
        with the given ID exists. The returned template includes all variant
        content fields (HTML, plain text, short) and the list of required
        variables.
        """
        ...

    async def find_by_id_and_version(self, template_id: str, version: int) -> Optional[Template]:
        """Retrieve a specific version of a template.

        This method is used when rendering notifications that were created
        before a template update, ensuring consistent output regardless of
        concurrent template modifications.
        """
        ...

    async def save(self, template: Template) -> Template:
        """Persist a template definition.

        If the template already exists, a new version is created. The
        returned template includes the assigned version number. This method
        does not modify existing versions.
        """
        ...

    async def find_by_channel(self, channel: str) -> list[Template]:
        """Retrieve all active templates for a given channel.

        Returns a list of templates that support the specified channel,
        filtered to only include active versions. This is used by the
        template management UI and the event consumer's template selection
        logic.
        """
        ...

    async def list_templates(self, limit: int = 50, offset: int = 0) -> list[Template]:
        """List all active templates with pagination.

        Returns a paginated list of active template definitions sorted by
        name. The limit and offset parameters control pagination.
        """
        ...
