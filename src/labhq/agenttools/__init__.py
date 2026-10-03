"""Engine tools for working agents, bound to the agent of the run that calls them.

`default_registry` carries the built-in tools. Roles add theirs with one `register` call.
"""

from labhq.agenttools.registry import (
    EVERY_ROLE,
    TOOLS_CONFIG_KEY,
    AgentToolRegistry,
    AgentToolSpec,
    ToolContext,
    UnknownAgentToolError,
    bind,
    tools_for,
)
from labhq.agenttools.whoami import WHOAMI

default_registry = AgentToolRegistry()
default_registry.register(WHOAMI)

__all__ = [
    "EVERY_ROLE",
    "TOOLS_CONFIG_KEY",
    "WHOAMI",
    "AgentToolRegistry",
    "AgentToolSpec",
    "ToolContext",
    "UnknownAgentToolError",
    "bind",
    "default_registry",
    "tools_for",
]
