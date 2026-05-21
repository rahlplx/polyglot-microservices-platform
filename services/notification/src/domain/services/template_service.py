"""
Template rendering service with Jinja2 support.

This module implements the template rendering pipeline for notifications.
Templates are loaded from the template repository (which stores them as
Jinja2 markup in PostgreSQL) and rendered with context variables provided
by the event consumer or API caller.

The service validates template variables before rendering to provide clear
error messages when required variables are missing. It supports multiple
output variants (HTML, plain text, short) and locale-specific templates.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..models.template import RenderedTemplate, Template, TemplateVariant
from ..ports.outbound.template_store import TemplateRepositoryPort
from ..services.notification_service import InvalidTemplateVarsError, TemplateNotFoundError

logger = logging.getLogger(__name__)


class TemplateService:
    """Service for rendering notification templates with Jinja2.

    The TemplateService loads templates from the repository, validates
    that all required variables are provided, and renders the template
    content for each supported variant. The rendered output is returned
    as a RenderedTemplate value object that can be passed to the channel
    sender for delivery.

    The service uses Jinja2 for template rendering, which supports template
    inheritance, conditional sections, loops, and filters. Template content
    is stored as Jinja2 markup in the database, and the rendering happens
    at send time to ensure that the most current template version is used
    (unless a specific version is requested for in-flight notifications).
    """

    def __init__(
        self,
        template_repo: TemplateRepositoryPort,
        jinja_env: Optional[object] = None,
    ) -> None:
        """Initialize the template service.

        Args:
            template_repo: Port for loading and storing templates.
            jinja_env: Optional Jinja2 Environment instance. If not provided,
                a default environment will be created lazily. The environment
                is injected to allow customization of template loading,
                caching, and security settings.
        """
        self._template_repo = template_repo
        self._jinja_env = jinja_env
        self._env_initialized = False

    def _get_jinja_env(self) -> object:
        """Lazily initialize the Jinja2 environment.

        The Jinja2 import is deferred to avoid a hard dependency in the
        domain layer. In production, the environment is provided by the
        DI container. In tests, a mock environment can be injected.
        This method creates a basic environment if none was provided.
        """
        if not self._env_initialized:
            if self._jinja_env is None:
                try:
                    from jinja2 import Environment, BaseLoader
                    self._jinja_env = Environment(
                        loader=BaseLoader(),
                        autoescape=True,
                        keep_trailing_newline=True,
                    )
                except ImportError:
                    logger.warning(
                        "Jinja2 not available, template rendering will be passthrough"
                    )
            self._env_initialized = True
        return self._jinja_env

    async def render(
        self,
        template_id: str,
        variables: dict[str, str],
        version: Optional[int] = None,
    ) -> RenderedTemplate:
        """Render a notification template with the given variables.

        Loads the template from the repository, validates that all required
        variables are present, and renders each supported variant. If a
        variant's template content is None, the corresponding output field
        in the RenderedTemplate will also be None.

        Args:
            template_id: The template to render.
            variables: Context variables for template substitution.
            version: Optional specific template version to render. If None,
                the active version is used.

        Returns:
            A RenderedTemplate with the rendered content for each variant.

        Raises:
            TemplateNotFoundError: If the template does not exist.
            InvalidTemplateVarsError: If required variables are missing.
        """
        # Load template
        if version is not None:
            template = await self._template_repo.find_by_id_and_version(
                template_id, version
            )
        else:
            template = await self._template_repo.find_by_id(template_id)

        if template is None:
            raise TemplateNotFoundError(
                f"Template not found: {template_id}"
            )

        # Validate required variables
        missing_vars = template.validate_vars(variables)
        if missing_vars:
            raise InvalidTemplateVarsError(
                f"Missing required template variables: {', '.join(missing_vars)}"
            )

        # Render each variant
        subject = self._render_string(template.subject_template, variables)
        html_content = self._render_variant(
            template, TemplateVariant.HTML, variables
        )
        plain_text_content = self._render_variant(
            template, TemplateVariant.PLAIN_TEXT, variables
        )
        short_content = self._render_variant(
            template, TemplateVariant.SHORT, variables
        )

        return RenderedTemplate(
            template_id=template.template_id,
            subject=subject,
            html_content=html_content,
            plain_text_content=plain_text_content,
            short_content=short_content,
        )

    async def validate(
        self,
        template_id: str,
        variables: dict[str, str],
    ) -> list[str]:
        """Validate that all required template variables are provided.

        Returns a list of missing variable names. An empty list indicates
        that the template can be rendered successfully with the given
        variables. This method does not render the template; it only
        checks that all required variables are present.

        Args:
            template_id: The template to validate against.
            variables: The variables to validate.

        Returns:
            A list of missing variable names.

        Raises:
            TemplateNotFoundError: If the template does not exist.
        """
        template = await self._template_repo.find_by_id(template_id)
        if template is None:
            raise TemplateNotFoundError(
                f"Template not found: {template_id}"
            )
        return template.validate_vars(variables)

    async def get_template(self, template_id: str) -> Template:
        """Retrieve a template definition by ID.

        Returns the template entity including all variant content and
        metadata. Raises TemplateNotFoundError if the template does not
        exist.

        Args:
            template_id: The template to retrieve.

        Returns:
            The Template entity.

        Raises:
            TemplateNotFoundError: If the template does not exist.
        """
        template = await self._template_repo.find_by_id(template_id)
        if template is None:
            raise TemplateNotFoundError(
                f"Template not found: {template_id}"
            )
        return template

    async def list_templates(
        self, channel: Optional[str] = None
    ) -> list[Template]:
        """List available templates, optionally filtered by channel.

        Args:
            channel: Optional channel filter. If provided, only templates
                that support the specified channel are returned.

        Returns:
            A list of Template entities.
        """
        if channel is not None:
            return await self._template_repo.find_by_channel(channel)
        return await self._template_repo.list_templates()

    def _render_variant(
        self,
        template: Template,
        variant: TemplateVariant,
        variables: dict[str, str],
    ) -> Optional[str]:
        """Render a single template variant.

        If the template does not support the requested variant, None is
        returned. Otherwise, the variant's Jinja2 markup is rendered with
        the provided variables.
        """
        content = template.get_template_content(variant)
        if content is None:
            return None
        return self._render_string(content, variables)

    def _render_string(self, template_str: Optional[str], variables: dict[str, str]) -> Optional[str]:
        """Render a Jinja2 template string with the given variables.

        If the Jinja2 library is not available, the template string is
        returned as-is with simple string formatting applied. This fallback
        ensures that the service degrades gracefully in environments where
        Jinja2 is not installed.
        """
        if template_str is None:
            return None

        env = self._get_jinja_env()
        if env is not None:
            try:
                from jinja2 import Template as JinjaTemplate
                jinja_template = JinjaTemplate(template_str)
                return jinja_template.render(**variables)
            except Exception as e:
                logger.error(
                    "Template rendering failed: %s", e, exc_info=True
                )
                raise
        else:
            # Fallback: simple string formatting
            try:
                return template_str.format(**variables)
            except KeyError:
                logger.warning(
                    "Fallback formatting failed for template, returning raw"
                )
                return template_str
