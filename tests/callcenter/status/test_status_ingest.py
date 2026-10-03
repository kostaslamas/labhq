from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.status import ingest_status, status_freshness
from labhq.clock import FakeClock
from labhq.db.models import AgentQuestion, Notification, RunEvent, StatusUpdate
from tests.db.factories import project_agent_task, run_for

QUESTION_FILE = "summary: Working.\nquestions:\n- Which branch?\n"


def write_status(worktree: Path, text: str) -> None:
    (worktree / ".labhq").mkdir(exist_ok=True)
    (worktree / ".labhq" / "status.md").write_text(text, encoding="utf-8")


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_a_question_read_twice_is_one_row_and_one_notification(
    session: AsyncSession, clock: FakeClock, tmp_path: Path
) -> None:
    _, agent, task = await project_agent_task(session, clock)
    write_status(tmp_path, QUESTION_FILE)

    for _ in range(2):
        await ingest_status(session, clock, agent_id=agent.id, task_id=task.id, worktree=tmp_path)
        await session.commit()

    [question] = (await session.scalars(select(AgentQuestion))).all()
    [notification] = (await session.scalars(select(Notification))).all()
    assert question.question == "Which branch?"
    assert (notification.kind, notification.subject) == (
        "agent_question",
        f"question:{question.id}",
    )
    assert notification.idempotency_key == f"agent_question:{question.id}"
    assert "Which branch?" in notification.body
    assert f"Q{question.id}" in notification.body
    assert await count(session, StatusUpdate) == 1


async def test_a_changed_file_stores_a_new_update_and_only_the_new_question(
    session: AsyncSession, clock: FakeClock, tmp_path: Path
) -> None:
    _, agent, task = await project_agent_task(session, clock)
    write_status(tmp_path, QUESTION_FILE)
    await ingest_status(session, clock, agent_id=agent.id, task_id=task.id, worktree=tmp_path)
    write_status(tmp_path, QUESTION_FILE + "- Which port?\n")

    result = await ingest_status(
        session, clock, agent_id=agent.id, task_id=task.id, worktree=tmp_path
    )
    await session.commit()

    assert [q.question for q in result.new_questions] == ["Which port?"]
    assert await count(session, StatusUpdate) == 2
    assert await count(session, Notification) == 2


async def test_no_file_stores_nothing(
    session: AsyncSession, clock: FakeClock, tmp_path: Path
) -> None:
    _, agent, task = await project_agent_task(session, clock)
    result = await ingest_status(
        session, clock, agent_id=agent.id, task_id=task.id, worktree=tmp_path
    )
    assert result.changed is False
    assert await count(session, StatusUpdate) == 0


async def test_a_status_is_fresh_only_while_newer_than_the_agents_last_event(
    session: AsyncSession, clock: FakeClock, tmp_path: Path
) -> None:
    _, agent, task = await project_agent_task(session, clock)
    run = await run_for(session, clock, agent, task)
    write_status(tmp_path, QUESTION_FILE)
    await ingest_status(session, clock, agent_id=agent.id, task_id=task.id, worktree=tmp_path)
    update = await session.scalar(select(StatusUpdate))
    assert update is not None
    # The file's own time is the real mtime; pin it so the rule is tested, not the wall clock.
    update.observed_at = clock.now()
    session.add(RunEvent(run_id=run.id, seq=1, kind="text", created_at=clock.now() - timedelta(1)))
    await session.commit()
    assert (await status_freshness(session, clock, agent.id)).fresh is True

    session.add(RunEvent(run_id=run.id, seq=2, kind="text", created_at=clock.now() + timedelta(1)))
    await session.commit()
    stale = await status_freshness(session, clock, agent.id)
    assert stale.fresh is False
    assert stale.age == timedelta(0)


async def test_an_agent_that_never_reported_is_stale_with_no_age(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent, _ = await project_agent_task(session, clock)
    result = await status_freshness(session, clock, agent.id)
    assert (result.update, result.fresh, result.age) == (None, False, None)
