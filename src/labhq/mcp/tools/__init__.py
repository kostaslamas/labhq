"""MCP tools. Each module registers its `ToolSpec`s on the default registry at import."""

from labhq.mcp.tools import actions, calls, inventory, meetings, questions, reports

__all__ = ["actions", "calls", "inventory", "meetings", "questions", "reports"]
