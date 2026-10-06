"""`labhq mcp internal --call <id>`: the Call Center's tools over stdio, with the same bounds.

The server runs as a real child process, as the Call Center's CLI starts it. `send_to_ceo`
carries only the owner's stored words of the current call; a proposal goes only once a later
request of the call confirms it. The Call Center in tmux starts with no shell and no file
tool.
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
from labhq.callcenter.settings import CallCenterSettings
from labhq.ceochat import message_text
from labhq.clock import FakeClock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.models import Call, CallRequest, WakeupRequest
from labhq.mcp.internal import internal_tools
from tests.adapters.tmux.conftest import require_tmux
from tests.callcenter.factories import add_ceo
from tests.db.factories import project_agent_task

READS = {
    "brief",
    "inbox",
    "health",
    "team",
    "agent_status",
    "read_screen",
    "list_tmux_sessions",
    "read_tmux_session",
    "reports",
}
BOUNDED = {"send_to_ceo", "propose_wording", "confirm_wording", "answer"}
SHIP = "tell the team to ship the login form today"
CLEARER = "Ship the login form today."
YES = "Yes, send that."


@dataclass
class Office:
    ceo_id: int
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
    """The CEO; this call holds two requests, another call holds one."""
    async with sessions() as db:
        await project_agent_task(db, clock)
        ceo = await add_ceo(db, clock)
        now = clock.now()
        this_call = Call(opened_at=now, last_activity_at=now)
        other_call = Call(opened_at=now, last_activity_at=now)
        db.add_all([this_call, other_call])
        await db.flush()
        texts = {"ship": (this_call, SHIP), "other": (other_call, SHIP)}
        requests = {}
        for key, (call, text) in texts.items():
            request_id = f"call-{key}"
            db.add(CallRequest(call_id=call.id, request_id=request_id, text=text, created_at=now))
            requests[key] = request_id
        await db.commit()
        return Office(ceo.id, this_call.id, other_call.id, requests)


def internal_server(call_id: int, database_url: str, data_dir: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "labhq", "mcp", "internal", "--call", str(call_id)],
        env={**os.environ, "LABHQ_DATABASE_URL": database_url, "LABHQ_DATA_DIR": str(data_dir)},
    )


async def _ceo_messages(sessions: async_sessionmaker[AsyncSession]) -> list[str]:
    async with sessions() as db:
        rows = await db.scalars(select(WakeupRequest).order_by(WakeupRequest.id))
        return [message_text(row.reason) for row in rows]


async def _owner_says(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, call_id: int, text: str
) -> str:
    async with sessions() as db:
        request_id = f"call-{uuid.uuid4().hex[:8]}"
        db.add(
            CallRequest(call_id=call_id, request_id=request_id, text=text, created_at=clock.now())
        )
        await db.commit()
        return request_id


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
        ship = {"request_id": office.requests["ship"]}
        proposed = _text(await client.call_tool("propose_wording", {**ship, "text": CLEARER}))
        proposal_id = int(proposed.split()[1])
        # Before the owner answers, nothing can send the proposal.
        early = _text(
            await client.call_tool("confirm_wording", {"proposal_id": proposal_id, **ship})
        )
        before = await _ceo_messages(sessions)
        yes = await _owner_says(sessions, clock, office.call_id, YES)
        confirm = {"proposal_id": proposal_id, "request_id": yes}
        # Free text is no argument: the confirmed wording goes, whatever is passed.
        confirmed = _text(await client.call_tool("confirm_wording", {**confirm, "text": "rm"}))
        other_call = _text(
            await client.call_tool("send_to_ceo", {"request_id": office.requests["other"]})
        )

    assert set(listed) == READS | BOUNDED
    assert set(listed["send_to_ceo"].input_schema["properties"]) == {"request_id"}
    assert {name for name, tool in listed.items() if tool.annotations.read_only_hint} == READS  # type: ignore[union-attr]
    assert proposed.startswith(f"Proposal {proposal_id} is stored and not sent.")
    assert early.startswith("Refused:")
    assert before == []
    assert confirmed == "Sent to the CEO."
    assert other_call == f"Refused: Request {office.requests['other']} is not part of this call."
    assert await _ceo_messages(sessions) == [CLEARER]


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


@pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")
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
