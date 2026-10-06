"""The engine runs a department task in the department folder: no worktree, no push approval."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select

from labhq.adapters import FakeAdapter, FakeScript, default_registry
from labhq.cli.context import Context
from labhq.cli.engine import Engine
from labhq.cli.statuses import ingest_statuses
from labhq.cli.workspace import plain_status_path
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, StatusUpdate
from labhq.departments import add_department_task, create_department
from labhq.settings import Settings


@pytest.fixture
async def context(database_url: str, tmp_path: Path, clock: FakeClock) -> AsyncIterator[Context]:
    engine = create_engine(database_url)
    try:
        yield Context(
            Settings(data_dir=tmp_path / "data", database_url=database_url),
            session_factory(engine),
            clock,
        )
    finally:
        await engine.dispose()


async def test_a_department_task_runs_in_its_folder_without_git(context: Context) -> None:
    now = context.clock.now()
    async with context.sessions() as db:
        ceo = Agent(
            role="ceo",
            title="CEO",
            adapter="fake",
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add(ceo)
        await db.flush()
        department, head = await create_department(
            db,
            context.clock,
            adapters=["fake"],
            ceo=ceo,
            data_dir=context.settings.data_dir,
            name="Research",
            kind="research",
            adapter="fake",
        )
        task = await add_department_task(
            db,
            context.clock,
            department,
            title="Market scan",
            deliverable="report",
            assignee=head.id,
        )
        await db.commit()
    script = FakeScript()
    registry = default_registry.copy()
    registry.register("fake", lambda: FakeAdapter(script), replace=True)

    report = await Engine(context, registry).run_pass()

    [request] = script.requests
    assert request.cwd == Path(department.folder)
    assert str(plain_status_path(task.id)) in request.prompt
    assert "You work in the Research department" in (request.system_prompt_append or "")
    assert [run.status for run in report.runs] == ["succeeded"]
    assert report.approvals == []
    assert not (context.settings.data_dir / "worktrees").exists()

    status = Path(department.folder) / plain_status_path(task.id)
    status.parent.mkdir(parents=True)
    status.write_text("summary: Scan under way.\n", encoding="utf-8")
    changed = await ingest_statuses(
        context.sessions, context.clock, context.settings, report.finished
    )
    assert len(changed) == 1
    async with context.sessions() as db:
        update = await db.scalar(select(StatusUpdate))
    assert update is not None
    assert update.fields["summary"] == "Scan under way."
