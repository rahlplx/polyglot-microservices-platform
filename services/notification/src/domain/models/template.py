"""
Template entity and related value objects for notification rendering.

This module defines the Template entity and the RenderedTemplate value object.
Templates are stored as Jinja2 markup in the persistence layer and rendered
at send time with context variables provided by the event consumer. The domain
model captures the template metadata and structure without depending on the
Jinja2 library itself -- actual rendering is performed by the template service
in the domain services layer.

Templates support multiple variants (HTML, plain text, SMS short format) and
locale-specific overrides. The variant system allows a single template
definition to produce channel-appropriate output without maintaining separate
templates for each channel.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class TemplateVariant(Enum):
    """Supported template output variants.

    Each variant corresponds to a specific output format. HTML is used for
    email body content with rich formatting. PLAIN_TEXT is used for email
    fallback and SMS messages. SHORT is a condensed format for push
    notification bodies. The variant determines which template content field
    is used during rendering.
    """

    HTML = "html"
    PLAIN_TEXT = "plain_text"
    SHORT = "short"


@dataclass
class Template:
    """Template entity representing a notification template definition.

    A template contains Jinja2 markup for each supported variant, along with
    metadata about the required variables, supported channels, and locale.
    Templates are versioned to ensure that in-flight notifications continue
    to use the template version that was active when the notification was
    created, preventing rendering errors due to concurrent template changes.

    The required_vars field lists variable names that must be provided during
    rendering. If a required variable is missing, the rendering step will
    raise an error rather than producing incomplete content. Optional variables
    should provide default values in the template itself using Jinja2's
    default filter.
    """

    template_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    channel: Optional[str] = None
    locale: str = "en-US"
    subject_template: Optional[str] = None
    html_template: Optional[str] = None
    plain_text_template: Optional[str] = None
    short_template: Optional[str] = None
    required_vars: list[str] = field(default_factory=list)
    version: int = 1
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def get_template_content(self, variant: TemplateVariant) -> Optional[str]:
        """Retrieve the template content for a specific variant.

        This method returns the Jinja2 markup for the requested variant, or
        None if the template does not support that variant. Callers should
        check the return value and fall back to an alternative variant if
        the preferred one is not available.
        """
        variant_map = {
            TemplateVariant.HTML: self.html_template,
            TemplateVariant.PLAIN_TEXT: self.plain_text_template,
            TemplateVariant.SHORT: self.short_template,
        }
        return variant_map.get(variant)

    def validate_vars(self, variables: dict[str, str]) -> list[str]:
        """Validate that all required template variables are provided.

        Returns a list of missing variable names. An empty list indicates
        that all required variables are present and the template can be
        rendered successfully. This validation is performed before rendering
        to fail fast and avoid partial template output.
        """
        missing = []
        for var_name in self.required_vars:
            if var_name not in variables:
                missing.append(var_name)
        return missing

    def supports_variant(self, variant: TemplateVariant) -> bool:
        """Check whether this template has content for the given variant.

        A template supports a variant if the corresponding content field is
        not None and not empty. This check is used by the template service
        to select an appropriate variant for rendering.
        """
        content = self.get_template_content(variant)
        return content is not None and len(content.strip()) > 0


@dataclass(frozen=True)
class RenderedTemplate:
    """Immutable value object representing a fully rendered notification template.

    After template rendering, this object carries the final content for each
    variant. The rendering service populates all available variants, and the
    channel adapter selects the appropriate variant for delivery. This
    separation ensures that rendering and delivery are decoupled.
    """

    template_id: str
    subject: Optional[str]
    html_content: Optional[str]
    plain_text_content: Optional[str]
    short_content: Optional[str]
    rendered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
