"""The Call Center agent: only its own tools, bound to its call, on its row's adapter."""

from sqlalchemy import select, update

from labhq.adapters import AgentTool, RunRequest
from labhq.adapters.claude import ClaudeAdapter
from labhq.callcenter.calls import ROLE, call_center_agent
from labhq.callcenter.calls.settings import CallAgentSettings
from labhq.db.models import Agent, Delivery
from tests.adapters.stub_sdk import CLI_PATH
from tests.callcenter.calls.conftest import Line
from tests.db.factories import project_agent_task

READS = {"brief", "inbox", "health", "team", "agent_status"}
BOUNDED = {"deliver", "interrupt", "answer"}


async def _tools(line: Line, question: str) -> dict[str, AgentTool]:
    await line.center.ask(question)
    await line.center.settle()
    return {tool.name: tool for tool in line.fake.requests[-1].tools}


async def test_the_agent_gets_reads_plus_the_bounded_tools_and_nothing_else(line: Line) -> None:
    tools = await _tools(line, "Status?")

    assert set(tools) == READS | BOUNDED
    assert {name for name, tool in tools.items() if tool.read_only} == READS


async def test_the_claude_adapter_serves_them_in_process_with_no_builtin_tools(
    line: Line,
) -> None:
    tools = await _tools(line, "Status?")

    options = ClaudeAdapter(cli_path=CLI_PATH, environ={}).options_for(
        RunRequest(prompt="hi", tools=list(tools.values()))
    )

    assert options.tools == []
    assert options.strict_mcp_config is True
    assert set(options.mcp_servers) == {"labhq"}
    assert options.mcp_servers["labhq"]["type"] == "sdk"
    assert sorted(options.allowed_tools) == sorted(f"mcp__labhq__{name}" for name in tools)


async def test_the_agent_starts_on_the_sdk_adapter_and_moving_it_is_configuration(
    line: Line,
) -> None:
    async with line.sessions() as db:
        agent = await call_center_agent(db, line.clock, CallAgentSettings())
        assert agent.adapter == "claude"
        # The row is the configuration: pointing it at another adapter is the whole move.
        await db.execute(update(Agent).where(Agent.role == ROLE).values(adapter="fake"))
        await db.commit()

    await _tools(line, "Status?")
    assert len(line.fake.requests) == 1


async def test_a_tool_reads_the_team_and_an_agents_status(line: Line) -> None:
    async with line.sessions() as db:
        _, worker, _ = await project_agent_task(db, line.clock)
        worker_id = worker.id
        await db.commit()
    tools = await _tools(line, "Who is working?")

    team = await tools["team"].handler({})
    worker_status = await tools["agent_status"].handler({"agent_id": worker_id})

    assert "Worker" in team and "Call Center" in team
    assert "has not written a status yet" in worker_status


async def test_a_refused_delivery_is_an_answer_the_agent_reads(line: Line) -> None:
    async with line.sessions() as db:
        _, worker, _ = await project_agent_task(db, line.clock)
        worker_id = worker.id
        await db.commit()
    tools = await _tools(line, "How is the build?")
    ticket = line.fake.requests[-1].prompt.split("Request ")[1].split(" ")[0]

    said = await tools["deliver"].handler({"request_id": ticket, "agent_id": worker_id})

    assert said.startswith("Refused:")
    async with line.sessions() as db:
        assert (await db.scalars(select(Delivery))).all() == []


async def test_the_tools_are_bound_to_their_own_call(line: Line) -> None:
    async with line.sessions() as db:
        _, worker, _ = await project_agent_task(db, line.clock)
        worker_id = worker.id
        await db.commit()
    other = await line.center.ask("Tell the worker to use main.")
    await line.center.settle()
    line.after_window()
    tools = await _tools(line, "Anything new?")

    said = await tools["deliver"].handler({"request_id": other.ticket, "agent_id": worker_id})

    assert said == f"Refused: Request {other.ticket} is not part of this call."
