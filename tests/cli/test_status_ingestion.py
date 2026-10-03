from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select

from labhq.adapters import FakeScript, RunRequest, default_registry
from labhq.cli.context import Context
from labhq.cli.engine import Engine
from labhq.cli.fake_worker import CommittingFakeAdapter
from labhq.cli.work import create_agent, create_project, create_task
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus
from labhq.db.models import AgentQuestion, Notification, StatusUpdate
from labhq.settings import Settings


class ReportingFakeAdapter(CommittingFakeAdapter):
    """A worker that keeps its status file current and asks one question."""

    async def start(self, request: RunRequest) -> None:
        assert request.cwd is not None
        (request.cwd / ".labhq").mkdir(exist_ok=True)
        (request.cwd / ".labhq" / "status.md").write_text(
            "summary: Working.\nquestions:\n- Which branch?\n", encoding="utf-8"
        )
        await super().start(request)


@pytest.fixture
async def context(database_url: str, data_dir: Path, clock: FakeClock) -> AsyncIterator[Context]:
    engine = create_engine(database_url)
    try:
        yield Context(
            Settings(data_dir=data_dir, database_url=database_url), session_factory(engine), clock
        )
    finally:
        await engine.dispose()


async def test_a_finished_run_ingests_its_status_file_and_the_question_once(
    context: Context, repo: Path
) -> None:
    registry = default_registry.copy()
    registry.register("fake", lambda: ReportingFakeAdapter(FakeScript()), replace=True)
    await create_project(context, "wired", repo, None)
    worker = await create_agent(
        context,
        project="wired",
        role="worker",
        title="Worker",
        adapter="fake",
        status=AgentStatus.ACTIVE,
    )
    await create_task(context, project="wired", title="Wire it", assignee=worker.id)

    await Engine(context, registry).run_pass()

    async with context.sessions() as db:
        [update] = (await db.scalars(select(StatusUpdate))).all()
        [question] = (await db.scalars(select(AgentQuestion))).all()
        notification = await db.scalar(
            select(Notification).where(Notification.kind == "agent_question")
        )
    assert notification is not None
    assert update.fields["summary"] == "Working."
    assert (question.question, question.agent_id) == ("Which branch?", worker.id)
    assert notification.subject == f"question:{question.id}"
