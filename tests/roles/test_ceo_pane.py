"""A persistent tmux CEO pane outlives the run its tool server was started for.

The pane's `labhq mcp agent --run N --follow-agent` is bound to the run it started with. On a
later turn that run is over, so the CEO's tools must resolve the CEO's current run, and still
act for the CEO only.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AgentTool
from labhq.agenttools.stdio import run_tools
from labhq.db.enums import RunStatus
from labhq.db.models import Run, RunEvent, Task
from tests.roles.conftest import Org


async def new_run(org: Org, agent_id: int, status: RunStatus) -> int:
    sessions: async_sessionmaker[AsyncSession] = org.sessions
    async with sessions() as db:
        run = Run(agent_id=agent_id, adapter="tmux", status=status, created_at=org.clock.now())
        db.add(run)
        await db.commit()
        return run.id


async def finish(org: Org, run_id: int) -> None:
    async with org.sessions() as db:
        (await db.get_one(Run, run_id)).status = RunStatus.SUCCEEDED
        await db.commit()


async def ceo_events(org: Org) -> list[RunEvent]:
    return [e for e in await org.all(RunEvent) if e.kind == "ceo_action"]


def tool(tools: list[AgentTool], name: str) -> AgentTool:
    (found,) = [t for t in tools if t.name == name]
    return found


async def test_the_ceos_tools_act_for_the_ceo_on_a_later_turn_in_the_same_pane(org: Org) -> None:
    first = await new_run(org, org.ceo, RunStatus.RUNNING)
    tools = await run_tools(org.tools, org.sessions, org.clock, first, follow_agent=True)
    priority = tool(tools, "set_priority")

    await priority.handler({"task": org.site_task, "priority": 1})
    assert [(e.run_id, e.payload["actor"]) for e in await ceo_events(org)] == [
        (first, f"agent:{org.ceo}")
    ]

    # Between turns the first run is over and there is no current one.
    await finish(org, first)
    assert "no active run" in await priority.handler({"task": org.site_task, "priority": 2})
    assert (await org.get(Task, org.site_task)).priority == 1

    # The next owner message starts a new run; the same server now acts under it.
    second = await new_run(org, org.ceo, RunStatus.RUNNING)
    await priority.handler({"task": org.site_task, "priority": 3})

    assert (await org.get(Task, org.site_task)).priority == 3
    assert [(e.run_id, e.payload["actor"]) for e in await ceo_events(org)] == [
        (first, f"agent:{org.ceo}"),
        (second, f"agent:{org.ceo}"),
    ]


async def test_the_pane_never_acts_for_another_agents_run(org: Org) -> None:
    ceo_run = await new_run(org, org.ceo, RunStatus.RUNNING)
    await new_run(org, org.manager, RunStatus.RUNNING)
    tools = await run_tools(org.tools, org.sessions, org.clock, ceo_run, follow_agent=True)

    answer = await tool(tools, "set_budget").handler({"scope": "agent", "id": org.ceo, "micros": 1})

    assert answer.startswith("Refused:")
    assert {e.run_id for e in await ceo_events(org)} <= {ceo_run}


async def test_the_pane_serves_the_ceos_org_tools_and_a_worker_gets_none_of_them(
    org: Org,
) -> None:
    ceo_run = await new_run(org, org.ceo, RunStatus.RUNNING)
    worker_run = await new_run(org, org.worker, RunStatus.RUNNING)

    ceo = {t.name for t in await run_tools(org.tools, org.sessions, org.clock, ceo_run)}
    worker = {t.name for t in await run_tools(org.tools, org.sessions, org.clock, worker_run)}

    assert {"add_project", "staff_team", "set_budget", "request_merge"} <= ceo
    assert not worker & {"add_project", "staff_team", "set_budget", "request_merge"}
