"""A project repository, an owner's tmux server running the fake CLI, labhq's private
tmux server, and the `adopt_agent` executor bound to this test's database."""

import os
import shutil
import sys
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters.tmux import (
    AgentKind,
    AgentKinds,
    RulesInjection,
    SessionIdSource,
    TmuxServer,
    TurnEnd,
    UsageSource,
    default_kinds,
)
from labhq.adoption import (
    ADOPT_AGENT,
    AdoptedChecks,
    AdoptionEngine,
    Adoptions,
    AdoptionSettings,
    adoption_executor,
)
from labhq.adoption.discovery import RunningAgent, find_running
from labhq.approvals import ApprovalService, default_executors
from labhq.clock import SystemClock
from labhq.db import create_engine, session_factory
from tests.worktrees.conftest import isolated_git, remote, repo  # noqa: F401  (fixtures)

FAKE_CLI = Path(__file__).with_name("fake_cli.py")
KIND = "fake-cli"
CLOCK = SystemClock()


def fake_kind(store: Path) -> AgentKind:
    script = (sys.executable, str(FAKE_CLI), "--store", str(store))
    return AgentKind(
        name=KIND,
        start=script,
        resume=None,
        session_id=SessionIdSource.SIGNAL,
        session_key="session",
        interrupt_keys=("C-c",),
        turn_end=TurnEnd.SIGNAL,
        usage_source=UsageSource.STATUSLINE,
        launch=None,
        hooks=None,
        usage_command=None,
        source="tests/adoption/fake_cli.py",
        continue_=(*script, "--signal", "{signal_path}", "--continue"),
        rules_injection=RulesInjection.FIRST_MESSAGE,
        compaction_pattern=r"^FAKE-COMPACTED$",
        processes=(FAKE_CLI.name,),
        continue_source="tests/adoption/fake_cli.py",
    )


def require_tmux() -> None:
    # A tmux test that skips would pass while proving nothing.
    if shutil.which("tmux") is None:
        pytest.fail("tmux is not installed; the adoption tests need it (CI installs it)")


def make_server(tmp_path: Path, label: str) -> TmuxServer:
    socket = f"labhq-{label}-{uuid.uuid4().hex[:10]}"
    return TmuxServer(socket=socket, state_dir=tmp_path / label)


async def wait_for(condition: Callable[[], bool], what: str, timeout: float = 15.0) -> None:
    for _ in range(int(timeout / 0.05)):
        if condition():
            return
        await CLOCK.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


@dataclass
class World:
    repo: Path
    store: Path
    kinds: AgentKinds
    owner: TmuxServer
    private: TmuxServer
    sessions: async_sessionmaker[AsyncSession]
    approvals: ApprovalService
    adoptions: Adoptions
    checks: AdoptedChecks
    settings: AdoptionSettings

    @property
    def drivers(self) -> list[str]:
        return lines(self.store / "drivers.log")

    @property
    def inbox(self) -> list[str]:
        return lines(self.store / "inbox.log")

    async def start_original(self, *, work: float = 0.0) -> RunningAgent:
        """The agent the owner started in their own tmux, in the project's main checkout."""
        argv = [sys.executable, str(FAKE_CLI), "--store", str(self.store), "--work", str(work)]
        before = len(self.drivers)
        name = f"owner-{before}"
        self.owner.new_session(name, cwd=self.repo, argv=argv, variables={})
        await wait_for(lambda: len(self.drivers) > before, "the original agent to start")
        pid = int(self.drivers[before].split()[1])
        return find_running(pid, self.kinds)

    async def approve(self, approval_id: int) -> None:
        await self.approvals.approve(approval_id, decider="owner", confirmation="cli")


@pytest.fixture
def private(tmp_path: Path) -> Iterator[TmuxServer]:
    require_tmux()
    server = make_server(tmp_path, "private")
    try:
        yield server
    finally:
        server.kill_server()


@pytest.fixture
def owner(tmp_path: Path) -> Iterator[TmuxServer]:
    require_tmux()
    server = make_server(tmp_path, "owner")
    try:
        yield server
    finally:
        server.kill_server()


@pytest.fixture
async def world(
    tmp_path: Path,
    repo: Path,  # noqa: F811
    database_url: str,
    owner: TmuxServer,
    private: TmuxServer,
) -> AsyncIterator[World]:
    store = tmp_path / "store"
    kinds = default_kinds.copy()
    kinds.register(fake_kind(store))
    settings = AdoptionSettings(
        owner_tmux_socket=owner.socket,
        poll_seconds=0.05,
        quiescence_seconds=0.5,
        turn_timeout_seconds=20,
        end_timeout_seconds=5,
        ready_seconds=0.3,
        ready_timeout_seconds=10,
        session_wait_seconds=5,
    )
    engine = AdoptionEngine(
        server=lambda: private,
        kinds=kinds,
        clock=CLOCK,
        database_url=lambda: database_url,
        settings=lambda: settings,
        environ=dict(os.environ),
    )
    executors = default_executors.copy()
    executors.register(ADOPT_AGENT, adoption_executor(engine), replace=True)
    db_engine = create_engine(database_url)
    sessions = session_factory(db_engine)
    approvals = ApprovalService(sessions, clock=CLOCK, executors=executors)
    try:
        yield World(
            repo=repo,
            store=store,
            kinds=kinds,
            owner=owner,
            private=private,
            sessions=sessions,
            approvals=approvals,
            adoptions=Adoptions(
                sessions, clock=CLOCK, approvals=approvals, kinds=kinds, settings=settings
            ),
            checks=AdoptedChecks(
                sessions, clock=CLOCK, server=private, kinds=kinds, settings=settings
            ),
            settings=settings,
        )
    finally:
        await db_engine.dispose()


async def adopt(world: World, *, work: float = 0.0) -> tuple[RunningAgent, int]:
    """Start the original agent, request its adoption and approve it; return the manager id."""
    original = await world.start_original(work=work)
    request = await world.adoptions.request(original.pid, project="site")
    await world.approve(request.approval.id)
    executed = await world.approvals.get(request.approval.id)
    assert executed.execution is not None, executed
    assert "agent_id" in executed.execution, executed.execution
    return original, int(executed.execution["agent_id"])
