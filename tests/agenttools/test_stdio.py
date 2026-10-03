"""`labhq mcp agent --run <id>` serves the run agent's tools over stdio to an MCP client."""

import os
import sys

from mcp import Client, StdioServerParameters
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
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

    assert [tool.name for tool in listed.tools] == ["whoami"]
    assert listed.tools[0].annotations is not None
    assert listed.tools[0].annotations.read_only_hint is True
    text = called.content[0]
    assert text.type == "text"
    assert text.text.startswith(f"You are agent {team.worker_id}, Worker, role worker.")
    assert missing.is_error
