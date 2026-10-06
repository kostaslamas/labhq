"""The roles at work: each role's instruction and tools (plan §2, §2.2; ADR 0005).

Importing this package registers the instructions in `labhq.prompts.default_roles` and the
tools in `labhq.agenttools.default_registry`. `register` does the same for other
registries, which is how tests bind the tools to their own services.
"""

from labhq.agenttools import AgentToolRegistry, AgentToolSpec
from labhq.agenttools import default_registry as default_tools
from labhq.prompts import RoleRegistry, default_roles
from labhq.roles.ceo_org import ceo_org_tools
from labhq.roles.common import RoleServices, agent_reference
from labhq.roles.instructions import INSTRUCTIONS, register_instructions
from labhq.roles.it import it_tools
from labhq.roles.org import ceo_tools, manager_tools
from labhq.roles.reports import report_tools
from labhq.roles.tasks import task_tools


def role_tools(services: RoleServices) -> list[AgentToolSpec]:
    return [
        *ceo_tools(services),
        *ceo_org_tools(services),
        *report_tools(),
        *manager_tools(services),
        *task_tools(),
        *it_tools(services),
    ]


def register(
    roles: RoleRegistry, tools: AgentToolRegistry, services: RoleServices | None = None
) -> None:
    register_instructions(roles)
    for spec in role_tools(services or RoleServices()):
        tools.register(spec)


register(default_roles, default_tools)

__all__ = [
    "INSTRUCTIONS",
    "RoleServices",
    "agent_reference",
    "register",
    "role_tools",
]
