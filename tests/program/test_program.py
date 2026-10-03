import asyncio
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.cli.context import Context
from labhq.cli.engine import Engine
from labhq.cli.work import create_agent, create_project, create_task
from labhq.cli.workspace import project_worktrees
from labhq.db.enums import NotificationStatus, RunStatus
from labhq.db.models import AgentQuestion, Notification, Project, Run
from labhq.notify import Dispatcher, NotifySettings, build_notifier, enqueue
from labhq.program import (
    LoopRegistry,
    Program,
    ProgramError,
    ProgramSettings,
    Services,
    default_loops,
)
from labhq.settings import Settings
from tests.program.conftest import Passes, SteppedClock, observed


class FakeServer:
    """Serves until told to exit, like uvicorn, and records whether it ever stopped."""

    def __init__(self, *, fail_after_start: bool = False) -> None:
        self._exit = asyncio.Event()
        self.fail_after_start = fail_after_start
        self.stopped = False
        self.started = asyncio.Event()

    @property
    def should_exit(self) -> bool:
        return self._exit.is_set()

    @should_exit.setter
    def should_exit(self, value: bool) -> None:
        if value:
            self._exit.set()

    async def serve(self) -> None:
        self.started.set()
        if self.fail_after_start:
            return
        try:
            await self._exit.wait()
        finally:
            self.stopped = True


class Outbound:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200)


@pytest.fixture
def outbound() -> Outbound:
    return Outbound()


@pytest.fixture
def context(
    sessions: async_sessionmaker[AsyncSession],
    stepped: SteppedClock,
    database_url: str,
    tmp_path: Path,
) -> Context:
    settings = Settings(data_dir=tmp_path / "data", database_url=database_url)
    return Context(settings, sessions, stepped)


@pytest.fixture
def services(context: Context, outbound: Outbound) -> Services:
    notify = NotifySettings(ntfy_topic="program-test")
    client = httpx.AsyncClient(transport=httpx.MockTransport(outbound))
    notifier = build_notifier(notify, client, context.settings.data_dir)
    dispatcher = Dispatcher(context.sessions, notifier, clock=context.clock, settings=notify)
    return Services(context, Engine(context), dispatcher)


def program_for(
    services: Services, loops: LoopRegistry[Services], server: FakeServer, clock: SteppedClock
) -> Program:
    return Program(services, loops, server, clock=clock, settings=ProgramSettings())


async def test_request_stop_ends_the_program_and_stops_server_and_loops(
    services: Services, stepped: SteppedClock
) -> None:
    passes = Passes()
    server = FakeServer()
    program = program_for(services, observed(default_loops, passes), server, stepped)
    running = asyncio.create_task(program.run(handle_signals=False))
    await server.started.wait()
    for name in ("scheduler", "notifications", "statuses"):
        await passes.reached(name, 1)

    program.request_stop()
    await running

    assert server.stopped


async def test_a_server_that_dies_is_an_error_not_a_silent_exit(
    services: Services, stepped: SteppedClock
) -> None:
    server = FakeServer(fail_after_start=True)
    program = program_for(services, default_loops, server, stepped)

    with pytest.raises(ProgramError, match="stopped unexpectedly"):
        await program.run(handle_signals=False)


async def test_a_failing_loop_leaves_the_other_loops_and_the_server_running(
    services: Services, stepped: SteppedClock
) -> None:
    passes = Passes()
    healthy = 0

    async def broken() -> None:
        raise RuntimeError("always fails")

    async def fine() -> None:
        nonlocal healthy
        healthy += 1

    loops: LoopRegistry[Services] = LoopRegistry()
    loops.register("broken", "scheduler_interval_seconds", lambda _: passes.watch("broken", broken))
    loops.register("fine", "scheduler_interval_seconds", lambda _: passes.watch("fine", fine))
    server = FakeServer()
    program = program_for(services, loops, server, stepped)
    running = asyncio.create_task(program.run(handle_signals=False))

    for count in (1, 2, 3):
        await passes.reached("broken", count)
        await passes.reached("fine", count)
        assert not server.stopped and not running.done()
        await stepped.tick(ProgramSettings().scheduler_interval_seconds)
    program.request_stop()
    await running

    assert healthy >= 3


async def test_a_pending_notification_is_sent_without_notify_flush(
    services: Services, stepped: SteppedClock, outbound: Outbound
) -> None:
    async with services.context.sessions() as db:
        await enqueue(
            db,
            kind="question",
            subject="question:1",
            title="Which branch?",
            body="An agent is waiting.",
            idempotency_key="program-test",
            now=stepped.now(),
        )
        await db.commit()
    passes = Passes()
    server = FakeServer()
    program = program_for(services, observed(default_loops, passes), server, stepped)
    running = asyncio.create_task(program.run(handle_signals=False))

    await passes.reached("notifications", 1)
    program.request_stop()
    await running

    assert len(outbound.requests) == 1
    async with services.context.sessions() as db:
        [row] = (await db.scalars(select(Notification))).all()
    assert row.status == NotificationStatus.SENT


async def test_a_new_question_in_a_status_file_is_ingested_on_the_timer(
    services: Services, stepped: SteppedClock, repo: Path
) -> None:
    context = services.context
    await create_project(context, "live", repo, None)
    agent = await create_agent(context, project="live", role="worker", title="W", adapter="fake")
    task = await create_task(context, project="live", title="Long job", assignee=agent.id)
    async with context.sessions() as db:
        project = await db.get_one(Project, task.project_id)
        db.add(
            Run(
                agent_id=agent.id,
                task_id=task.id,
                adapter="fake",
                status=RunStatus.RUNNING,
                created_at=stepped.now(),
                started_at=stepped.now(),
                heartbeat_at=stepped.now(),
            )
        )
        await db.commit()
    worktree = project_worktrees(context.settings, project).create(task.id, task.title)
    passes = Passes()
    program = program_for(services, observed(default_loops, passes), FakeServer(), stepped)
    running = asyncio.create_task(program.run(handle_signals=False))
    await passes.reached("statuses", 1)
    async with context.sessions() as db:
        assert (await db.scalars(select(AgentQuestion))).all() == []

    # The agent writes its question while the run is still live; no run finishes.
    status_file = worktree.path / ".labhq" / "status.md"
    status_file.parent.mkdir(exist_ok=True)
    status_file.write_text("summary: Working.\nquestions:\n- Which branch?\n", encoding="utf-8")
    await stepped.tick(ProgramSettings().status_interval_seconds)
    await passes.reached("statuses", 2)
    program.request_stop()
    await running

    async with context.sessions() as db:
        [question] = (await db.scalars(select(AgentQuestion))).all()
        run = (await db.scalars(select(Run))).one()
    assert question.question == "Which branch?"
    assert run.status is RunStatus.RUNNING
