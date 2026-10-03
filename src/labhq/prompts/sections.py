"""The built-in sections: the role instruction first, then the output style for its reader."""

from labhq.db.models import Agent, Task
from labhq.economy.graphify import GRAPHIFY_POSITION, GRAPHIFY_SECTION, default_section
from labhq.economy.style import StyleRegistry, styled_system_prompt
from labhq.economy.style import default_registry as default_styles
from labhq.prompts.registry import PromptRegistry, SectionBuilder
from labhq.prompts.roles import RoleRegistry, default_roles

ROLE_SECTION = "role"
OUTPUT_STYLE_SECTION = "output_style"
ROLE_POSITION = 100
OUTPUT_STYLE_POSITION = 200


def role_section(roles: RoleRegistry) -> SectionBuilder:
    def build(agent: Agent, task: Task | None) -> str | None:
        return roles.instruction(agent.role)

    return build


def output_style_section(styles: StyleRegistry) -> SectionBuilder:
    def build(agent: Agent, task: Task | None) -> str | None:
        # The role text is its own section, so the style is appended to nothing here.
        return styled_system_prompt("", agent.config, styles)

    return build


def builtin_registry(
    roles: RoleRegistry = default_roles, styles: StyleRegistry | None = None
) -> PromptRegistry:
    registry = PromptRegistry()
    registry.register(ROLE_SECTION, role_section(roles), position=ROLE_POSITION)
    registry.register(
        OUTPUT_STYLE_SECTION,
        output_style_section(styles if styles is not None else default_styles()),
        position=OUTPUT_STYLE_POSITION,
    )
    registry.register(GRAPHIFY_SECTION, default_section, position=GRAPHIFY_POSITION)
    return registry


default_registry = builtin_registry()
