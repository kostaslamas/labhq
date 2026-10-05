"""`labhq mcp agent --run <id>` serves the run agent's tools over stdio to an MCP client."""

import os
import sys

from mcp import Client, StdioServerParameters
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.agenttools.registry import AgentToolRegistry, AgentToolSpec, ToolContext
from labhq.agenttools.stdio import run_tools
from labhq.agenttools.whoami import NoArguments
from labhq.clock import FakeClock
from labhq.db.enums import RunStatus
from labhq.db.models import Agent, Run
from tests.agenttools.conftest import Team


async def queued_run(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, team: Team
) -> int:
    async with sessions() as db:
        worker = await db.get_one(Agent, team.worker_id)
        run = Run(agent_id=worker.id, task_id=team.task_id, adapter="fake", created_at=clock.now())
        db.add(run)
        await db.commit()
        return run.id


def server_for(run_id: int, database_url: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "labhq", "mcp", "agent", "--run", str(run_id)],
        env={**os.environ, "LABHQ_DATABASE_URL": database_url},
    )


async def test_an_mcp_client_lists_and_calls_the_run_agents_tools(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    team: Team,
    database_url: str,
) -> None:
    run_id = await queued_run(sessions, clock, team)

    async with Client(server_for(run_id, database_url), read_timeout_seconds=30) as client:
        listed = await client.list_tools()
        # The client names another agent; the server answers for the run's agent.
        called = await client.call_tool("whoami", {"agent_id": team.manager_id})
        missing = await client.call_tool("assign", {})

    assert {tool.name for tool in listed.tools} == {"whoami", "task_overview", "report_task"}
    whoami = next(tool for tool in listed.tools if tool.name == "whoami")
    assert whoami.annotations is not None
    assert whoami.annotations.read_only_hint is True
    text = called.content[0]
    assert text.type == "text"
    assert text.text.startswith(f"You are agent {team.worker_id}, Worker, role worker.")
    assert missing.is_error


async def test_persistent_tool_server_uses_the_current_run_on_each_call(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, team: Team
) -> None:
    async def current_run(context: ToolContext, arguments: NoArguments) -> str:
        return str(context.run_id)

    registry = AgentToolRegistry()
    registry.register(
        AgentToolSpec(
            name="current_run",
            description="Show the current run",
            input_model=NoArguments,
            roles=frozenset({"worker"}),
            read_only=True,
            handler=current_run,
        )
    )
    first = await queued_run(sessions, clock, team)
    async with sessions() as db:
        (await db.get_one(Run, first)).status = RunStatus.RUNNING
        await db.commit()
    [tool] = await run_tools(registry, sessions, clock, first, follow_agent=True)
    assert await tool.handler({}) == str(first)

    async with sessions() as db:
        (await db.get_one(Run, first)).status = RunStatus.SUCCEEDED
        await db.commit()
    assert "no active run" in await tool.handler({})

    second = await queued_run(sessions, clock, team)
    async with sessions() as db:
        (await db.get_one(Run, second)).status = RunStatus.RUNNING
        await db.commit()
    assert await tool.handler({}) == str(second)
