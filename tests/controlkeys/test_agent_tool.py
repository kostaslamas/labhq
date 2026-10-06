"""Agents may press Escape on their direct reports and nothing more."""

import pytest

from labhq.agenttools import AgentToolRegistry, ToolContext, bind
from labhq.controlkeys import ControlKeyError, agent_sender, control_key_tools
from tests.controlkeys.conftest import World


def key_tool(world: World, caller: str):  # type: ignore[no-untyped-def]
    registry = AgentToolRegistry()
    for spec in control_key_tools(lambda context: world.service):
        registry.register(spec)
    context = ToolContext(
        agent_id=world.ids[caller], run_id=None, sessions=world.sessions, clock=world.clock
    )
    (spec,) = registry
    return bind(spec, context)


async def test_a_manager_sends_escape_to_a_direct_report(world: World) -> None:
    reply = await key_tool(world, "manager_a").handler(
        {"agent": world.ids["lead_a"], "key": "escape"}
    )

    assert reply == f"Sent escape to agent {world.ids['lead_a']}."
    assert world.panes.sent == [(world.pane("lead_a"), ("Escape",), False)]


@pytest.mark.parametrize("target", ["worker_a", "lead_b", "manager_b", "manager_a", "ceo"], ids=str)
async def test_a_manager_cannot_reach_anyone_but_its_direct_reports(
    world: World, target: str
) -> None:
    reply = await key_tool(world, "manager_a").handler(
        {"agent": world.ids[target], "key": "escape"}
    )

    assert reply.startswith("Refused:")
    assert world.panes.sent == []


async def test_the_ceo_reaches_its_managers_but_not_their_teams(world: World) -> None:
    ceo = key_tool(world, "ceo")

    assert (await ceo.handler({"agent": world.ids["manager_b"], "key": "escape"})).startswith(
        "Sent"
    )
    assert (await ceo.handler({"agent": world.ids["lead_b"], "key": "escape"})).startswith(
        "Refused"
    )


@pytest.mark.parametrize("key", ["shift_tab", "ctrl_c", "BTab", "hello"])
async def test_an_agent_never_sends_another_key(world: World, key: str) -> None:
    reply = await key_tool(world, "manager_a").handler({"agent": world.ids["lead_a"], "key": key})

    assert reply.startswith("Invalid arguments")
    assert world.panes.sent == []


@pytest.mark.parametrize("key", ["shift_tab", "ctrl_c"])
async def test_the_service_refuses_owner_only_keys_from_an_agent(world: World, key: str) -> None:
    with pytest.raises(ControlKeyError) as refused:
        await world.service.send(agent_sender(world.ids["manager_a"]), world.ids["lead_a"], key)

    assert refused.value.code == "not_permitted"
    assert world.panes.sent == []


async def test_a_worker_has_no_key_tool_and_cannot_send(world: World) -> None:
    from labhq.agenttools import default_registry
    from labhq.prompts import RoleRegistry
    from labhq.roles import register

    registry = AgentToolRegistry()
    register(RoleRegistry(), registry)
    assert [s.name for s in registry.for_agent("worker", {}) if s.name == "send_control_key"] == []
    for role in ("ceo", "manager", "lead", "head"):
        assert "send_control_key" in [s.name for s in registry.for_agent(role, {})]
    assert default_registry is not registry

    with pytest.raises(ControlKeyError) as refused:
        await world.service.send(
            agent_sender(world.ids["worker_a"]), world.ids["worker_b"], "escape"
        )
    assert refused.value.code == "not_permitted"
