"""A delegated objective can descend, return for review, and await the owner."""

from labhq.db.enums import TaskStatus, WakeupStatus
from labhq.db.models import Notification, Task
from labhq.work.progress import owner_decide
from tests.roles.conftest import Org


async def _task(org: Org, title: str) -> Task:
    return next(task for task in await org.all(Task) if task.title == title)


async def test_objective_travels_down_and_returns_to_the_owner(org: Org) -> None:
    await org.call("delegate_task", org.ceo, project="site", title="Ship login")
    root = await _task(org, "Ship login")
    assert root.assignee_id == org.manager

    await org.call(
        "create_task", org.manager, title="Implement login", parent=root.id, assignee=org.lead
    )
    lead_task = await _task(org, "Implement login")
    await org.call(
        "create_task",
        org.lead,
        title="Write login code",
        parent=lead_task.id,
        assignee=org.worker,
    )
    leaf = await _task(org, "Write login code")
    assert (lead_task.parent_id, leaf.parent_id) == (root.id, lead_task.id)

    early = await org.call("report_task", org.manager, task=root.id, summary="Done")
    assert "unfinished child" in early

    await org.call("report_task", org.worker, task=leaf.id, summary="Commit abc123")
    assert (await org.get(Task, leaf.id)).status is TaskStatus.IN_REVIEW
    assert any(w.agent_id == org.lead and w.task_id == lead_task.id for w in await org.wakeups())
    await org.call("review_task", org.lead, task=leaf.id, accept=True, feedback="Tests pass")
    await org.call("report_task", org.lead, task=lead_task.id, summary="Reviewed abc123")
    await org.call("review_task", org.manager, task=lead_task.id, accept=True, feedback="Ready")
    await org.call("report_task", org.manager, task=root.id, summary="Login works")
    assert any(w.agent_id == org.ceo and w.task_id == root.id for w in await org.wakeups())

    recommendation = await org.call(
        "review_task", org.ceo, task=root.id, accept=True, feedback="Meets the objective"
    )
    assert "only the owner" in recommendation
    assert (await org.get(Task, root.id)).status is TaskStatus.IN_REVIEW
    assert len(await org.all(Notification)) == 1

    async with org.sessions() as db:
        task = await db.get_one(Task, root.id)
        await owner_decide(db, org.clock, task, accept=True, feedback="Accepted")
        await db.commit()
    assert (await org.get(Task, root.id)).status is TaskStatus.DONE


async def test_feedback_reopens_the_task_and_wakes_its_assignee(org: Org) -> None:
    await org.call("delegate_task", org.ceo, project="site", title="Improve search")
    task = await _task(org, "Improve search")
    await org.call("report_task", org.manager, task=task.id, summary="First version")
    await org.call(
        "review_task", org.ceo, task=task.id, accept=False, feedback="Missing empty state"
    )
    assert (await org.get(Task, task.id)).status is TaskStatus.TODO
    assert any(
        w.agent_id == org.manager and w.task_id == task.id and w.status == WakeupStatus.PENDING
        for w in await org.wakeups()
    )

    await org.call("report_task", org.manager, task=task.id, summary="Added empty state")
    await org.call("review_task", org.ceo, task=task.id, accept=True, feedback="Ready for owner")
    async with org.sessions() as db:
        current = await db.get_one(Task, task.id)
        await owner_decide(db, org.clock, current, accept=False, feedback="Add keyboard support")
        await db.commit()
    assert (await org.get(Task, task.id)).status is TaskStatus.TODO


async def test_only_assignee_reports_and_only_reviewer_reviews(org: Org) -> None:
    await org.call("delegate_task", org.ceo, project="site", title="Scope check")
    task = await _task(org, "Scope check")
    wrong_report = await org.call("report_task", org.worker, task=task.id, summary="Done")
    assert wrong_report == f"Refused: task {task.id} is not assigned to you"
    await org.call("report_task", org.manager, task=task.id, summary="Ready")
    wrong_review = await org.call(
        "review_task", org.shop_manager, task=task.id, accept=True, feedback="Sure"
    )
    assert wrong_review == f"Refused: task {task.id} is not yours to review"
