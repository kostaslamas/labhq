"""Which tools an agent gets, and who a tool acts for."""

from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import FakeAdapter, FakeScript
from labhq.adapters import default_registry as adapters
from labhq.agenttools import (
    WHOAMI,
    AgentToolRegistry,
    AgentToolSpec,
    ToolContext,
    UnknownAgentToolError,
    bind,
)
from labhq.agenttools import default_registry as builtin_tools
from labhq.clock import FakeClock
from labhq.db.models import Agent
from labhq.memory import AgentMemory
from labhq.runs import RunService
from tests.agenttools.conftest import Team


class ActAs(BaseModel):
    # A model may well pass an agent id; the tool must not act on it.
    agent_id: int | None = None


async def acting_agent(context: ToolContext, arguments: ActAs) -> str:
    return str(context.agent_id)


def spec(name: str, roles: set[str], *, read_only: bool = True) -> AgentToolSpec:
    return AgentToolSpec(
        name=name,
        description=f"The {name} tool.",
        input_model=ActAs,
        roles=frozenset(roles),
        read_only=read_only,
        handler=acting_agent,
    )


def registry() -> AgentToolRegistry:
    tools = AgentToolRegistry()
    tools.register(WHOAMI)
    tools.register(spec("assign", {"ceo"}, read_only=False))
    tools.register(spec("propose_team", {"manager"}, read_only=False))
    tools.register(spec("add_rule", {"it"}, read_only=False))
    tools.register(spec("read_metrics", {"it"}))
    return tools


def names(specs: list[AgentToolSpec]) -> set[str]:
    return {item.name for item in specs}


def test_an_agent_sees_its_roles_tools_only() -> None:
    assert names(registry().for_agent("manager", {})) == {"whoami", "propose_team"}
    assert names(registry().for_agent("worker", {})) == {"whoami"}


def test_an_agent_also_sees_the_tools_its_config_names() -> None:
    chosen = registry().for_agent("worker", {"tools": ["assign"]})
    assert names(chosen) == {"whoami", "assign"}


def test_a_read_only_agent_sees_read_only_tools_only() -> None:
    config = {"permission_mode": "read_only", "tools": ["assign"]}
    assert names(registry().for_agent("it", config)) == {"whoami", "read_metrics"}


def test_an_unknown_or_malformed_tool_name_is_refused() -> None:
    with pytest.raises(UnknownAgentToolError, match="nope"):
        registry().for_agent("worker", {"tools": ["nope"]})
    with pytest.raises(ValueError, match="list of tool names"):
        registry().for_agent("worker", {"tools": "assign"})


def test_a_tool_name_registers_once() -> None:
    with pytest.raises(ValueError, match="already registered"):
        registry().register(WHOAMI)


async def test_a_tool_acts_as_the_calling_agent_whatever_its_arguments_say(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, team: Team
) -> None:
    context = ToolContext(team.worker_id, None, sessions, clock)
    tool = bind(spec("act", {"worker"}), context)
    assert await tool.handler({"agent_id": team.manager_id}) == str(team.worker_id)
    assert "Invalid arguments" in await tool.handler({"agent_id": "the manager"})


async def test_whoami_answers_for_the_caller_not_the_agent_it_names(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, team: Team
) -> None:
    context = ToolContext(team.worker_id, None, sessions, clock)
    answer = await bind(WHOAMI, context).handler({"agent_id": team.manager_id})
    assert answer == (
        f"You are agent {team.worker_id}, Worker, role worker.\n"
        f"Project: demo (id {team.project_id}).\n"
        f"Manager: agent {team.manager_id}, Manager (manager)."
    )


async def test_a_run_hands_its_adapter_the_agents_tools_bound_to_it(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, team: Team, tmp_path: Path
) -> None:
    script = FakeScript()
    registry_ = adapters.copy()
    registry_.register("fake", lambda: FakeAdapter(script), replace=True)
    async with sessions() as db:
        await db.execute(
            update(Agent).where(Agent.id == team.manager_id).values(config={"tools": ["assign"]})
        )
        await db.commit()
    # A manager keeps memory; its home stays in this test's directory.
    memory = AgentMemory(tmp_path / "agents")
    service = RunService(
        sessions, clock=clock, registry=registry_, memory=memory, agent_tools=registry()
    )

    await service.execute(agent_id=team.manager_id, task_id=team.task_id, prompt="go")

    (request,) = script.requests
    tools = {tool.name: tool for tool in request.agent_tools}
    assert set(tools) == {"whoami", "propose_team", "assign"}
    assert await tools["assign"].handler({"agent_id": team.worker_id}) == str(team.manager_id)


def test_whoami_is_built_in() -> None:
    assert "whoami" in names(builtin_tools.for_agent("any role", {}))
