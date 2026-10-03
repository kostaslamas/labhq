"""A manager at work in a real private tmux server, and a reader of its screen."""

import os
import sys
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters.tmux import TmuxServer
from labhq.adapters.tmux.adapter import session_name
from labhq.callcenter.screens import ScreenLog, ScreenReader
from labhq.clock import FakeClock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import RunStatus
from labhq.db.models import Agent, Project, Run, RunEvent, StatusUpdate, Task
from tests.adapters.tmux.conftest import require_tmux

FAKE_WORKER = Path(__file__).with_name("fake_worker.py")
SUMMARY = "Wiring the login form of the demo project"
# Waiting on a child process's output, not on a scheduler: real time, bounded.
SCREEN_TIMEOUT_SECONDS = 15
POLL_SECONDS = 0.05


class SpyServer(TmuxServer):
    """The private server, recording every tmux command labhq sends through it."""

    def __init__(self, *, socket: str, state_dir: Path) -> None:
        super().__init__(socket=socket, state_dir=state_dir)
        self.commands: list[tuple[str, ...]] = []

    def run(self, *args: str, client_env: object = None) -> str:
        self.commands.append(args)
        return super().run(*args, client_env=client_env)  # type: ignore[arg-type]

    def keys_sent(self) -> list[tuple[str, ...]]:
        return [command for command in self.commands if command[0] == "send-keys"]


@pytest.fixture
def spy_server(tmp_path: Path) -> Iterator[SpyServer]:
    require_tmux()
    server = SpyServer(socket=f"labhq-test-{uuid.uuid4().hex[:12]}", state_dir=tmp_path / "tmux")
    try:
        yield server
    finally:
        server.kill_server()


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@dataclass
class Office:
    sessions: async_sessionmaker[AsyncSession]
    clock: FakeClock
    server: SpyServer
    reader: ScreenReader
    workdir: Path
    project_id: int
    manager_id: int
    task_id: int
    run_id: int
    seen: list[str] = field(default_factory=list)

    def screen(self) -> str:
        return self.server.capture(session_name(self.run_id))

    async def progress(self, line: str) -> None:
        """The manager prints `line`, as its work goes on; no key reaches its pane."""
        with (self.workdir / "progress").open("w", encoding="utf-8") as pipe:
            pipe.write(f"{line}\n")
        await self.wait_for(line)

    async def wait_for(self, text: str) -> None:
        await until(lambda: text in self.screen(), f"{text!r} on the manager's screen")


async def until(condition: Callable[[], bool], what: str) -> None:
    """Wait for a child process to show `what`; bounded real time, as the tmux adapter polls."""
    clock = SystemClock()
    deadline = clock.now() + timedelta(seconds=SCREEN_TIMEOUT_SECONDS)
    while not condition():
        if clock.now() > deadline:
            raise AssertionError(f"never saw {what}")
        await clock.sleep(POLL_SECONDS)


@pytest.fixture
async def office(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    spy_server: SpyServer,
    tmp_path: Path,
) -> Office:
    """A manager running in tmux since its last event, with a status written a minute later."""
    async with sessions() as db:
        now = clock.now()
        project = Project(name="demo", repo_path="/srv/demo", created_at=now, updated_at=now)
        db.add(project)
        await db.flush()
        manager = Agent(
            project_id=project.id,
            role="manager",
            title="Manager",
            adapter="tmux",
            config={"agent": "claude-code"},
            created_at=now,
            updated_at=now,
        )
        task = Task(project_id=project.id, title="Login form", created_at=now, updated_at=now)
        db.add_all([manager, task])
        await db.flush()
        run = Run(
            agent_id=manager.id,
            task_id=task.id,
            adapter="tmux",
            status=RunStatus.RUNNING,
            created_at=now,
            started_at=now,
        )
        db.add(run)
        await db.flush()
        db.add(RunEvent(run_id=run.id, seq=1, kind="screen", payload={}, created_at=now))
        clock.advance(timedelta(minutes=1))
        db.add(
            StatusUpdate(
                agent_id=manager.id,
                task_id=task.id,
                fields={"summary": SUMMARY, "next": ["error states"]},
                fingerprint="f" * 64,
                observed_at=clock.now(),
            )
        )
        await db.commit()
        ids = (project.id, manager.id, task.id, run.id)
    workdir = tmp_path / "manager"
    workdir.mkdir()
    os.mkfifo(workdir / "progress")
    spy_server.new_session(
        session_name(ids[3]),
        cwd=workdir,
        argv=[sys.executable, str(FAKE_WORKER)],
        variables={},
    )
    reader = ScreenReader(spy_server, ScreenLog(tmp_path / "screens"))
    office = Office(sessions, clock, spy_server, reader, workdir, *ids)
    await office.wait_for("working on the login form")
    return office
