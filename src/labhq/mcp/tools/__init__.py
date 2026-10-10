"""MCP tools. Each module registers its `ToolSpec`s on the default registry at import."""

from labhq.mcp.tools import (
    actions,
    calls,
    channels,
    inventory,
    meetings,
    models,
    questions,
    reports,
)

__all__ = [
    "actions",
    "calls",
    "channels",
    "inventory",
    "meetings",
    "models",
    "questions",
    "reports",
]
