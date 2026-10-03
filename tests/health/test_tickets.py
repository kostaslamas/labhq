"""Rule actions: a `ticket` incident opens one task with a diagnosis, `notify` one message."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.enums import HealthRuleAction, IncidentStatus, TaskStatus
from labhq.db.models import Comment, Incident, Notification, Project, Task
from labhq.health.incidents import Transition, evaluate_rules
from labhq.health.tickets import INFRA_PROJECT
from tests.health.factories import add_host, add_rule, add_samples

DISK_OVER_90 = {"metric": "disk.percent", "comparison": ">", "value": 90}


async def _all[T](session: AsyncSession, model: type[T]) -> list[T]:
    return list((await session.scalars(select(model))).all())


async def test_a_ticket_rule_opens_one_task_across_repeated_violations(
    session: AsyncSession, clock: FakeClock, data_dir: Path
) -> None:
    host = await add_host(session, clock, "nas")
    rule = await add_rule(session, clock, params=DISK_OVER_90, action=HealthRuleAction.TICKET)
    began = clock.now()
    await add_samples(session, host, "disk.percent", [(began, 93.0)], subject="/data")
    await evaluate_rules(session, clock)
    for value in (95.0, 97.0):
        clock.advance(300)
        await add_samples(session, host, "disk.percent", [(clock.now(), value)], subject="/data")
        assert await evaluate_rules(session, clock) == []
    await session.commit()

    [task] = await _all(session, Task)
    [incident] = await _all(session, Incident)
    [project] = await _all(session, Project)
    assert incident.task_id == task.id
    assert (project.name, task.project_id) == (INFRA_PROJECT, project.id)
    assert Path(project.repo_path) == data_dir / "infra"
    assert Path(project.repo_path).is_dir()
    assert task.status is TaskStatus.TODO
    assert task.title == f"nas: {rule.name}"
    for expected in (
        "Host: nas",
        f"Rule: {rule.id}",
        "Reason: Test rule",
        f"Began: {began.isoformat()}",
        '"latest": {"/data": 93.0}',
        "Recent samples of disk.percent:",
        f"- {began.isoformat()} /data 93.0",
    ):
        assert expected in task.description
    assert await _all(session, Notification) == []


async def test_recovery_resolves_the_incident_and_comments_on_the_task(
    session: AsyncSession, clock: FakeClock
) -> None:
    host = await add_host(session, clock, "nas")
    await add_rule(session, clock, params=DISK_OVER_90, action=HealthRuleAction.TICKET)
    await add_samples(session, host, "disk.percent", [(clock.now(), 93.0)])
    await evaluate_rules(session, clock)

    clock.advance(600)
    await add_samples(session, host, "disk.percent", [(clock.now(), 60.0)])
    [change] = await evaluate_rules(session, clock)

    assert change.transition is Transition.RESOLVED
    assert change.incident.status is IncidentStatus.RESOLVED
    [task] = await _all(session, Task)
    [comment] = await _all(session, Comment)
    assert comment.task_id == task.id
    assert "Recovered" in comment.body
    # Closing the task stays with the IT agent or the owner.
    assert task.status is TaskStatus.TODO


async def test_tickets_from_several_incidents_share_the_infra_project(
    session: AsyncSession, clock: FakeClock
) -> None:
    for name in ("one", "two"):
        host = await add_host(session, clock, name)
        await add_samples(session, host, "disk.percent", [(clock.now(), 99.0)])
    await add_rule(session, clock, params=DISK_OVER_90, action=HealthRuleAction.TICKET)

    await evaluate_rules(session, clock)

    tasks = await _all(session, Task)
    assert len(tasks) == 2
    assert len(await _all(session, Project)) == 1
    assert {incident.task_id for incident in await _all(session, Incident)} == {
        task.id for task in tasks
    }


async def test_a_notify_rule_queues_exactly_one_notification(
    session: AsyncSession, clock: FakeClock
) -> None:
    host = await add_host(session, clock, "nas")
    rule = await add_rule(session, clock, params=DISK_OVER_90, action=HealthRuleAction.NOTIFY)
    for value in (93.0, 95.0, 97.0):
        await add_samples(session, host, "disk.percent", [(clock.now(), value)])
        await evaluate_rules(session, clock)
        clock.advance(300)
    await session.commit()

    [notification] = await _all(session, Notification)
    [incident] = await _all(session, Incident)
    assert notification.kind == "incident_opened"
    assert notification.subject == f"incident:{incident.id}"
    assert "nas" in notification.title
    assert rule.reason in notification.body
    assert incident.task_id is None
    assert await _all(session, Task) == []
