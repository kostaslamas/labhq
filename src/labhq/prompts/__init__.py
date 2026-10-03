"""What a run appends to its adapter's system prompt, assembled from registered sections."""

from labhq.prompts.registry import DuplicateSectionError, PromptRegistry, Section, SectionBuilder
from labhq.prompts.roles import DuplicateRoleError, RoleRegistry, default_roles
from labhq.prompts.sections import (
    OUTPUT_STYLE_POSITION,
    OUTPUT_STYLE_SECTION,
    ROLE_POSITION,
    ROLE_SECTION,
    builtin_registry,
    default_registry,
)

__all__ = [
    "OUTPUT_STYLE_POSITION",
    "OUTPUT_STYLE_SECTION",
    "ROLE_POSITION",
    "ROLE_SECTION",
    "DuplicateRoleError",
    "DuplicateSectionError",
    "PromptRegistry",
    "RoleRegistry",
    "Section",
    "SectionBuilder",
    "builtin_registry",
    "default_registry",
    "default_roles",
]
