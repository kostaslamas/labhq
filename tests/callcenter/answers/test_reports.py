"""`reports`: status from what workers and their supervisors reported, without waking anyone."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers import reports
from labhq.clock import FakeClock
from labhq.db.enums import AgentStatus, RunStatus, TaskStatus
from labhq.db.models import Agent, Comment, Run, StatusUpdate, Task, WakeupRequest
from labhq.speech import speakable
from tests.callcenter.factories import add_ceo
from tests.db.factories import project_agent_task


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def _comment(
    session: AsyncSession, clock: FakeClock, task: Task, agent: Agent, body: str, minutes: int
) -> None:
    at = clock.now() - timedelta(minutes=minutes)
    session.add(Comment(task_id=task.id, author_agent_id=agent.id, body=body, created_at=at))


async def seed_reports(session: AsyncSession, clock: FakeClock) -> dict[str, int]:
    """A worker reports to its manager, the manager reviews it and reports to the CEO."""
    project, worker, task = await project_agent_task(session, clock)
    ceo = await add_ceo(session, clock)
    now = clock.now()
    manager = Agent(
        project_id=project.id,
        role="manager",
        title="Ada",
        adapter="fake",
        reports_to=ceo.id,
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session.add(manager)
    await session.flush()
    root = Task(
        project_id=project.id,
        title="Login epic",
        assignee_id=manager.id,
        status=TaskStatus.IN_REVIEW,
        created_at=now,
        updated_at=now,
    )
    session.add(root)
    await session.flush()
    task.parent_id, task.assignee_id, task.status = root.id, worker.id, TaskStatus.DONE
    await _comment(session, clock, task, worker, "Login form done, tests green.", 30)
    await _comment(session, clock, task, manager, "Accepted the login form.", 20)
    await _comment(session, clock, root, manager, "Login epic is ready for the CEO.", 5)
    # The worker ran again after its report: the report may be stale.
    session.add(
        Run(
            agent_id=worker.id,
            task_id=task.id,
            adapter="fake",
            status=RunStatus.RUNNING,
            created_at=now - timedelta(minutes=2),
            started_at=now - timedelta(minutes=2),
        )
    )
    await session.commit()
    return {"ceo": ceo.id, "task": task.id, "root": root.id}


async def test_status_comes_from_the_latest_reports_with_reporter_and_age(
    session: AsyncSession, clock: FakeClock
) -> None:
    ids = await seed_reports(session, clock)

    text = await reports(session, clock)

    assert speakable(text) == text
    assert text.startswith("Reports in demo.")
    # The manager's report to the CEO is newer than its review, so it is the one told.
    assert f"Ada, the manager reported on T{ids['root']}, Login epic, 5 minutes ago." in text
    assert "It said: Login epic is ready for the CEO." in text
    assert "Accepted the login form" not in text
    assert f"Worker reported on T{ids['task']}, First task, 30 minutes ago." in text
    assert "It said: Login form done, tests green." in text
    assert "The task is done." in text
    assert "Its last run is running, from 2 minutes ago." in text
    assert "It has run since this report, so the report may be stale." in text


async def test_a_supervisors_review_is_named_as_a_review(
    session: AsyncSession, clock: FakeClock
) -> None:
    project, worker, task = await project_agent_task(session, clock)
    now = clock.now()
    lead = Agent(
        project_id=project.id,
        role="lead",
        title="Lin",
        adapter="fake",
        created_at=now,
        updated_at=now,
    )
    session.add(lead)
    await session.flush()
    task.assignee_id = worker.id
    await _comment(session, clock, task, lead, "Send it back, the tests fail.", 61)
    await session.commit()

    text = await reports(session, clock, "demo")

    assert f"Lin, the lead reviewed on T{task.id}, First task, 1 hour ago." in text


async def test_a_status_file_counts_as_a_report(session: AsyncSession, clock: FakeClock) -> None:
    _, worker, task = await project_agent_task(session, clock)
    session.add(
        StatusUpdate(
            agent_id=worker.id,
            task_id=task.id,
            fields={"summary": "Wiring the form."},
            fingerprint="f1",
            observed_at=clock.now() - timedelta(minutes=3),
        )
    )
    await session.commit()

    text = await reports(session, clock)

    assert f"Worker wrote in its status on T{task.id}, First task, 3 minutes ago." in text


async def test_answering_wakes_neither_the_ceo_nor_anyone_else(
    session: AsyncSession, clock: FakeClock
) -> None:
    await seed_reports(session, clock)
    wakeups, runs = await _count(session, WakeupRequest), await _count(session, Run)

    await reports(session, clock)
    await reports(session, clock, "demo")

    assert (await _count(session, WakeupRequest), await _count(session, Run)) == (wakeups, runs)


async def test_no_reports_and_unknown_projects_are_said_plainly(
    session: AsyncSession, clock: FakeClock
) -> None:
    assert await reports(session, clock) == "There are no projects yet."
    await project_agent_task(session, clock)
    await session.commit()

    assert await reports(session, clock) == "In demo, nobody has reported yet."
    assert (await reports(session, clock, "ghost")).startswith("I could not find that project.")
