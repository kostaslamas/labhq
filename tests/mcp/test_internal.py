"""`labhq mcp internal --call <id>`: the Call Center's tools over stdio, with the same bounds.

The server runs as a real child process, as the Call Center's CLI starts it. `deliver`
carries only the owner's stored words of the current call, to an agent the owner named or
one with a pending question; `interrupt` needs the owner's request in the same call; every
delivery leaves a row. The Call Center in tmux starts with no shell and no file tool.
"""

import json
import os
import sys
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import default_registry
from labhq.adapters.tmux import TmuxAdapter, TmuxError, TmuxServer, default_kinds
from labhq.callcenter.calls import CallCenter, TicketState
from labhq.callcenter.calls.settings import CallAgentSettings
from labhq.callcenter.questions import raise_question
from labhq.callcenter.settings import CallCenterSettings
from labhq.clock import FakeClock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.models import Agent, Call, CallRequest, Delivery
from labhq.mcp.internal import internal_tools
from tests.adapters.tmux.conftest import require_tmux
from tests.db.factories import project_agent_task

READS = {"brief", "inbox", "health", "team", "agent_status", "read_screen"}
BOUNDED = {"deliver", "interrupt", "answer"}
SHIP = "Tell the Manager to ship the login form today."
STOP = "Interrupt the Manager and tell it to stop the deploy."


@dataclass
class Office:
    manager_id: int
    worker_id: int
    worker_task_id: int
    call_id: int
    other_call_id: int
    requests: dict[str, str]


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def office(sessions: async_sessionmaker[AsyncSession], clock: FakeClock) -> Office:
    """A manager and a worker; this call holds two requests, another call holds one."""
    async with sessions() as db:
        project, worker, task = await project_agent_task(db, clock)
        now = clock.now()
        manager = Agent(
            project_id=project.id,
            role="manager",
            title="Manager",
            adapter="fake",
            created_at=now,
            updated_at=now,
        )
        this_call = Call(opened_at=now, last_activity_at=now)
        other_call = Call(opened_at=now, last_activity_at=now)
        db.add_all([manager, this_call, other_call])
        await db.flush()
        texts = {"ship": (this_call, SHIP), "stop": (this_call, STOP), "other": (other_call, SHIP)}
        requests = {}
        for key, (call, text) in texts.items():
            request_id = f"call-{key}"
            db.add(CallRequest(call_id=call.id, request_id=request_id, text=text, created_at=now))
            requests[key] = request_id
        await db.commit()
        return Office(manager.id, worker.id, task.id, this_call.id, other_call.id, requests)


def internal_server(call_id: int, database_url: str, data_dir: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "labhq", "mcp", "internal", "--call", str(call_id)],
        env={**os.environ, "LABHQ_DATABASE_URL": database_url, "LABHQ_DATA_DIR": str(data_dir)},
    )


async def _deliveries(sessions: async_sessionmaker[AsyncSession]) -> list[Delivery]:
    async with sessions() as db:
        return list((await db.scalars(select(Delivery).order_by(Delivery.id))).all())


def _text(result: object) -> str:
    content = result.content[0]  # type: ignore[attr-defined]
    assert content.type == "text"
    return str(content.text)


async def test_the_stdio_server_serves_the_call_tools_with_their_bounds(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    office: Office,
    database_url: str,
    data_dir: Path,
) -> None:
    server = internal_server(office.call_id, database_url, data_dir)
    async with Client(server, read_timeout_seconds=30) as client:
        listed = {tool.name: tool for tool in (await client.list_tools()).tools}
        manager = {"request_id": office.requests["ship"], "agent_id": office.manager_id}
        # Free text is no argument of `deliver`: the stored words go, whatever is passed.
        delivered = _text(await client.call_tool("deliver", {**manager, "text": "rm -rf /"}))
        other_call = _text(
            await client.call_tool(
                "deliver", {"request_id": office.requests["other"], "agent_id": office.manager_id}
            )
        )
        to_worker = {"request_id": office.requests["ship"], "agent_id": office.worker_id}
        unnamed = _text(await client.call_tool("deliver", to_worker))
        unasked = _text(await client.call_tool("interrupt", manager))
        async with sessions() as db:
            await raise_question(
                db,
                clock,
                agent_id=office.worker_id,
                task_id=office.worker_task_id,
                text="Which session lifetime do we want?",
            )
            await db.commit()
        asking = _text(await client.call_tool("deliver", to_worker))
        stop = {"request_id": office.requests["stop"], "agent_id": office.manager_id}
        interrupted = _text(await client.call_tool("interrupt", stop))

    assert set(listed) == READS | BOUNDED
    for name in BOUNDED - {"answer"}:
        assert set(listed[name].input_schema["properties"]) == {"request_id", "agent_id"}
    assert {name for name, tool in listed.items() if tool.annotations.read_only_hint} == READS  # type: ignore[union-attr]
    assert delivered.startswith("Delivered to Manager")
    assert other_call == f"Refused: Request {office.requests['other']} is not part of this call."
    assert unnamed.startswith("Refused: The owner did not name Worker")
    assert unasked.startswith("Refused: The owner did not ask for an interrupt")
    assert asking.startswith("Delivered to Worker")
    # This process holds no running agent: the words wait for the end of the manager's turn.
    assert interrupted.startswith("Could not interrupt Manager from here")

    rows = await _deliveries(sessions)
    assert [(row.request_id, row.recipient_agent_id, row.text) for row in rows] == [
        (office.requests["ship"], office.manager_id, SHIP),
        (office.requests["ship"], office.worker_id, SHIP),
        (office.requests["stop"], office.manager_id, STOP),
    ]
    assert {row.call_id for row in rows} == {office.call_id}
    assert [row.interrupted for row in rows] == [False, False, False]


async def test_an_unknown_call_gets_no_tools(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, office: Office
) -> None:
    with pytest.raises(LookupError, match="there is no call 999"):
        await internal_tools(sessions, clock, 999, screens=None)


class RecordingServer(TmuxServer):
    """Records the start command and the MCP configuration the CLI would read, then stops."""

    def __init__(self, state_dir: Path) -> None:
        super().__init__(socket=f"labhq-test-{uuid.uuid4().hex[:12]}", state_dir=state_dir)
        self.argv: list[str] = []
        self.mcp_config: dict[str, object] = {}
        self.mcp_mode = 0

    def new_session(
        self,
        name: str,
        *,
        cwd: Path,
        argv: Sequence[str],
        variables: Mapping[str, str],
        client_env: Mapping[str, str] | None = None,
    ) -> None:
        self.argv = list(argv)
        path = Path(argv[argv.index("--mcp-config") + 1])
        self.mcp_config = json.loads(path.read_text(encoding="utf-8"))
        self.mcp_mode = path.stat().st_mode & 0o777
        raise TmuxError("recorded; the test runs no Claude Code")


async def test_the_call_center_in_tmux_has_no_shell_and_no_file_tool(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    database_url: str,
    tmp_path: Path,
) -> None:
    require_tmux()
    server = RecordingServer(tmp_path / "tmux")
    environ = {"PATH": os.environ["PATH"], "LABHQ_DATABASE_URL": database_url}
    registry = default_registry.copy()
    registry.register(
        "tmux",
        lambda: TmuxAdapter(
            server=server, kinds=default_kinds, clock=SystemClock(), environ=environ
        ),
        replace=True,
    )
    center = CallCenter(
        sessions,
        clock,
        adapters=registry,
        workdir=tmp_path / "callcenter",
        settings=CallCenterSettings(),
        # The defaults: the Call Center's row is on the tmux adapter, as Claude Code.
        agent_settings=CallAgentSettings(),
        screens=None,
    )
    ticket = await center.ask("What is the manager doing?")
    await center.settle()
    await center.close()

    argv = server.argv
    assert argv[0] == "claude"
    # `--tools ""` takes away every built-in tool: Bash, Edit, Write, Read and the rest.
    assert argv[argv.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert not {"--allowedTools", "--disallowedTools", "--mcp"} & set(argv)
    servers = server.mcp_config["mcpServers"]
    assert isinstance(servers, dict)
    assert set(servers) == {"labhq", "labhq-agent"}
    own = servers["labhq"]
    assert own["type"] == "stdio" and own["command"] == sys.executable
    assert own["args"] == ["-m", "labhq", "mcp", "internal", "--call", str(ticket.call_id)]
    assert own["env"] == {"LABHQ_DATABASE_URL": database_url}
    assert servers["labhq-agent"]["args"][:4] == ["-m", "labhq", "mcp", "agent"]
    assert server.mcp_mode == 0o600
    # The start failed on purpose; the ticket says so instead of hanging.
    assert (await center.reply(ticket.ticket)).state is TicketState.FAILED
