"""The owner MCP never exposes a tool that belongs to the CEO or any other agent (ADR 0009)."""

import labhq.roles  # noqa: F401  (registers the agent tools)
from labhq.agenttools import default_registry as agent_tools
from labhq.mcp.tools.registry import default_registry as owner_tools


def test_no_agent_tool_is_an_owner_tool() -> None:
    owner = {spec.name for spec in owner_tools}
    agent = {spec.name for spec in agent_tools}

    assert agent, "the agent tools did not register; the check would pass on nothing"
    assert "propose_decision_room" in agent
    assert owner.isdisjoint(agent)


def test_the_owner_has_no_tool_that_opens_or_speaks_in_a_decision_room() -> None:
    owner = {spec.name for spec in owner_tools}

    assert not {name for name in owner if "room" in name or "decision" in name}
