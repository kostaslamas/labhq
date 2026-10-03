"""Two calls at once are two Call Center agents in two tmux sessions; a follow-up resumes.

The Call Center runs a fake CLI on the `tmux` adapter in a real private server. Each call's
CLI is given the call's own stdio tool server and no built-in tools.
"""

import fcntl
import json
import os
import shlex
import sys
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import IO

import pytest
from sqlalchemy import select, update

from labhq.adapters import default_registry
from labhq.adapters.tmux import (
    AgentKind,
    SessionIdSource,
    TmuxAdapter,
    TurnEnd,
    UsageSource,
    default_kinds,
)
from labhq.adapters.tmux.adapter import session_name, split_session
from labhq.adapters.tmux.agents import TOOL_LAUNCHES, ToolLaunch, ToolServer
from labhq.callcenter.calls import CallCenter, Ticket, TicketState, call_center_agent
from labhq.callcenter.calls.settings import CallAgentSettings
from labhq.callcenter.settings import CallCenterSettings
from labhq.clock import FakeClock, SystemClock
from labhq.db.enums import RunStatus
from labhq.db.models import Agent, Call, Run, RunEvent
from tests.callcenter.screens.conftest import (
    POLL_SECONDS,
    SCREEN_TIMEOUT_SECONDS,
    SpyServer,
    until,
)

FAKE_CALL_CENTER = Path(__file__).with_name("fake_call_center.py")
WINDOW = CallCenterSettings(call_window_seconds=300, ticket_expiry_seconds=3600)
FAST = {"poll_seconds": 0.05, "quiescence_seconds": 0.5, "interrupt_settle_seconds": 0.5}


def fake_mcp(run_dir: Path, servers: Sequence[ToolServer]) -> list[str]:
    return ["--mcp", json.dumps([list(server.argv[1:]) for server in servers])]


def fake_cli(directory: Path) -> str:
    """The fake as one program, since a launch's words go right after the program name."""
    program = directory / "fake-call-center"
    command = shlex.join([sys.executable, str(FAKE_CALL_CENTER)])
    program.write_text(f'#!/bin/sh\nexec {command} "$@"\n', encoding="utf-8")
    program.chmod(0o755)
    return str(program)


def fake_kind(program: str) -> AgentKind:
    script = (program,)
    return AgentKind(
        name="fake-call-center",
        start=(*script, "--session", "{session_id}", "{prompt}"),
        resume=(*script, "--resume", "{session_id}", "{prompt}"),
        session_id=SessionIdSource.ASSIGNED,
        interrupt_keys=("C-c",),
        turn_end=TurnEnd.PATTERN,
        turn_end_pattern=r"^LABHQ-FAKE-TURN-END$",
        usage_source=UsageSource.SCREEN,
        launch=None,
        hooks=None,
        usage_command=None,
        source="tests/callcenter/screens/fake_call_center.py",
        tool_launch="fake_mcp",
    )


@dataclass
class Line:
    center: CallCenter
    server: SpyServer
    clock: FakeClock
    workdir: Path
    # Held with an exclusive lock: every fake Call Center waits for it to be released.
    gate: IO[str]

    async def runs(self) -> list[Run]:
        async with self.center.sessions() as db:
            return list((await db.scalars(select(Run).order_by(Run.id))).all())

    async def screen_of(self, run_id: int) -> str:
        async with self.center.sessions() as db:
            events = await db.scalars(select(RunEvent).where(RunEvent.run_id == run_id))
            return "\n".join(line for event in events for line in event.payload.get("lines", []))

    async def live_sessions(self, count: int) -> list[int]:
        """Wait until `count` Call Center runs hold a tmux session at the same time."""
        alive: list[int] = []

        async def check() -> None:
            running = [run.id for run in await self.runs() if run.status is RunStatus.RUNNING]
            alive[:] = [run for run in running if self.server.has_session(session_name(run))]

        clock = SystemClock()
        deadline = clock.now() + timedelta(seconds=SCREEN_TIMEOUT_SECONDS)
        while clock.now() < deadline:
            await check()
            if len(alive) == count:
                return alive
            await clock.sleep(POLL_SECONDS)
        raise AssertionError(f"expected {count} live Call Center sessions, saw {alive}")

    def open_line(self) -> None:
        self.gate.close()


@pytest.fixture
async def line(
    sessions: object,
    clock: FakeClock,
    spy_server: SpyServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Line]:
    monkeypatch.setitem(
        TOOL_LAUNCHES,
        "fake_mcp",
        ToolLaunch(attach=fake_mcp, exclusive=("--no-builtin-tools",), source="tests"),
    )
    kinds = default_kinds.copy()
    kinds.register(fake_kind(fake_cli(tmp_path)))
    registry = default_registry.copy()
    registry.register(
        "tmux",
        lambda: TmuxAdapter(
            server=spy_server, kinds=kinds, clock=SystemClock(), environ=dict(os.environ)
        ),
        replace=True,
    )
    workdir = tmp_path / "callcenter"
    workdir.mkdir()
    gate = (workdir / "line").open("a")
    fcntl.flock(gate, fcntl.LOCK_EX)
    center = CallCenter(
        sessions,  # type: ignore[arg-type]
        clock,
        adapters=registry,
        workdir=workdir,
        settings=WINDOW,
        agent_settings=CallAgentSettings(agent_adapter="tmux", agent_kind="fake-call-center"),
        screens=None,
    )
    try:
        yield Line(center, spy_server, clock, workdir, gate)
    finally:
        gate.close()
        await center.close()


async def _fast_agent(line: Line) -> None:
    """The Call Center's row, made before the first call, polling its pane quickly."""
    async with line.center.sessions() as db:
        agent = await call_center_agent(db, line.clock, line.center.agent_settings)
        await db.execute(
            update(Agent).where(Agent.id == agent.id).values(config={**agent.config, **FAST})
        )
        await db.commit()


async def _call(line: Line, ticket: Ticket) -> Call:
    async with line.center.sessions() as db:
        return await db.get_one(Call, ticket.call_id)


async def test_two_calls_at_once_are_two_agents_in_two_tmux_sessions(line: Line) -> None:
    await _fast_agent(line)
    first = await line.center.ask("What is the manager doing?")
    [first_run] = await line.live_sessions(1)
    # The first call's turn outlasts its window, so the next question opens a second call.
    line.clock.advance(timedelta(seconds=WINDOW.call_window_seconds + 1))
    second = await line.center.ask("Who is blocked?")
    live = await line.live_sessions(2)

    assert second.call_id != first.call_id
    second_run = next(run for run in live if run != first_run)
    for run, ticket in ((first_run, first), (second_run, second)):
        served = f"'-m labhq mcp internal --call {ticket.call_id}'"
        await until(lambda r=run, s=served: s in line.server.capture(session_name(r)), served)
        screen = line.server.capture(session_name(run))
        assert "builtin-tools=False" in screen and "resumed=False" in screen

    line.open_line()
    await line.center.settle()
    assert (await line.center.reply(first.ticket)).state is TicketState.READY
    assert (await line.center.reply(second.ticket)).state is TicketState.READY
    first_call, second_call = await _call(line, first), await _call(line, second)
    assert first_call.session_id and second_call.session_id
    assert first_call.session_id != second_call.session_id
    assert line.server.keys_sent() == []


async def test_a_second_question_within_the_window_resumes_the_same_session(line: Line) -> None:
    line.open_line()
    await _fast_agent(line)
    first = await line.center.ask("What is the manager doing?")
    await line.center.settle()
    line.clock.advance(timedelta(seconds=120))
    follow_up = await line.center.ask("And what is next for it?")
    await line.center.settle()

    assert follow_up.call_id == first.call_id
    opening, resumed = await line.runs()
    call = await _call(line, first)
    assert resumed.session_id_before == opening.session_id_after == call.session_id
    _, session = split_session(call.session_id)
    assert f"session={session} resumed=True" in await line.screen_of(resumed.id)
    assert (await line.center.reply(follow_up.ticket)).state is TicketState.READY
