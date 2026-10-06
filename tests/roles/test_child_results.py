"""A result reaches the parent as a short pointer; the parent reads it with `task_overview`."""

import pytest
from sqlalchemy import select

from labhq.db.enums import TaskStatus, WakeupSource, WakeupStatus
from labhq.db.models import Task, WakeupRequest
from labhq.scheduler import default_sources
from labhq.work.settings import get_work_settings
from tests.roles.conftest import Org


async def _task(org: Org, title: str) -> Task:
    return next(task for task in await org.all(Task) if task.title == title)


async def _pending(org: Org, agent_id: int) -> list[WakeupRequest]:
    return [
        w
        for w in await org.wakeups()
        if w.agent_id == agent_id and w.status is WakeupStatus.PENDING
    ]


async def _prompt(org: Org, request: WakeupRequest) -> str:
    task = await org.get(Task, request.task_id) if request.task_id else None
    return default_sources.handler(request.source).prompt(request, task)


async def _settle(org: Org) -> None:
    """The assignment wakeups ran already: only what comes after is under test."""
    async with org.sessions() as db:
        for request in await db.scalars(select(WakeupRequest)):
            request.status = WakeupStatus.DISPATCHED
        await db.commit()


async def _parent_with_children(org: Org) -> tuple[Task, Task, Task]:
    await org.call("delegate_task", org.ceo, project="site", title="Ship login")
    root = await _task(org, "Ship login")
    for title in ("Write code", "Write docs"):
        await org.call("create_task", org.manager, title=title, parent=root.id, assignee=org.worker)
    await _settle(org)
    return root, await _task(org, "Write code"), await _task(org, "Write docs")


async def test_a_child_report_wakes_the_parent_with_the_pointer_only(org: Org) -> None:
    root, code, _ = await _parent_with_children(org)

    await org.call("report_task", org.worker, task=code.id, summary="SECRET report text")

    [wakeup] = await _pending(org, org.manager)
    assert (wakeup.source, wakeup.task_id) == (WakeupSource.CHILD_REPORT, root.id)
    assert await _prompt(org, wakeup) == (
        f'Subtask #{code.id} "Write code" reported: ready for review. Read it with task_overview.'
    )


async def test_a_blocked_child_says_blocked(org: Org) -> None:
    _, code, _ = await _parent_with_children(org)

    await org.call("report_task", org.worker, task=code.id, summary="No access", blocked=True)

    [wakeup] = await _pending(org, org.manager)
    assert await _prompt(org, wakeup) == (
        f'Subtask #{code.id} "Write code" reported: blocked. Read it with task_overview.'
    )


async def test_children_reporting_before_the_parent_runs_share_one_prompt(org: Org) -> None:
    _, code, docs = await _parent_with_children(org)

    await org.call("report_task", org.worker, task=code.id, summary="Code done")
    await org.call("report_task", org.worker, task=docs.id, summary="Docs done", blocked=True)
    await org.call("report_task", org.worker, task=code.id, summary="Code done again")

    [wakeup] = await _pending(org, org.manager)
    assert (await _prompt(org, wakeup)).splitlines() == [
        f'Subtask #{code.id} "Write code" reported: ready for review. Read it with task_overview.',
        f'Subtask #{docs.id} "Write docs" reported: blocked. Read it with task_overview.',
    ]


async def test_returned_work_points_the_assignee_at_the_feedback(org: Org) -> None:
    await org.call("delegate_task", org.ceo, project="site", title="Ship login")
    root = await _task(org, "Ship login")
    await _settle(org)
    await org.call("report_task", org.manager, task=root.id, summary="First try")
    await org.call("review_task", org.ceo, task=root.id, accept=False, feedback="SECRET feedback")

    returned = [
        w for w in await _pending(org, org.manager) if w.source is WakeupSource.TASK_RETURNED
    ]
    [wakeup] = returned
    assert wakeup.task_id == root.id
    assert await _prompt(org, wakeup) == (
        f"Task #{root.id} was returned. Read the feedback with task_overview."
    )


async def test_overview_shows_every_childs_latest_report_with_author_and_time(org: Org) -> None:
    root, code, docs = await _parent_with_children(org)
    await org.call("report_task", org.worker, task=code.id, summary="First draft")
    org.clock.advance(60)
    await org.call("review_task", org.manager, task=code.id, accept=False, feedback="Add tests")
    await org.call("report_task", org.worker, task=code.id, summary="Tests added")
    await org.call("report_task", org.worker, task=docs.id, summary="Docs ready")

    overview = await org.call("task_overview", org.manager, task=root.id)

    assert f"- #{code.id} Write code [{TaskStatus.IN_REVIEW}]: agent {org.worker} at " in overview
    assert "UTC: Tests added" in overview
    assert "First draft" not in overview
    assert f"- #{docs.id} Write docs [{TaskStatus.IN_REVIEW}]: agent {org.worker} at " in overview
    assert "UTC: Docs ready" in overview


async def test_overview_limits_the_tasks_own_reports_from_settings(
    org: Org, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABHQ_WORK_OVERVIEW_REPORTS", "2")
    get_work_settings.cache_clear()
    try:
        await org.call("delegate_task", org.ceo, project="site", title="Ship login")
        root = await _task(org, "Ship login")
        for index in range(3):
            await org.call("report_task", org.manager, task=root.id, summary=f"try {index}")
            await org.call(
                "review_task", org.ceo, task=root.id, accept=False, feedback=f"no {index}"
            )
        overview = await org.call("task_overview", org.manager, task=root.id)
    finally:
        get_work_settings.cache_clear()

    reports = overview.split("Reports: ", 1)[1]
    assert reports.count("agent ") == 2
    assert "no 2" in reports and "try 2" in reports


async def test_each_level_of_the_chain_is_woken_once_and_reads_the_result(org: Org) -> None:
    root, code, docs = await _parent_with_children(org)

    await org.call("report_task", org.worker, task=code.id, summary="Commit abc123")
    [to_manager] = await _pending(org, org.manager)
    assert to_manager.task_id == root.id
    manager_view = await org.call("task_overview", org.manager, task=root.id)
    assert "Commit abc123" in manager_view

    await org.call("review_task", org.manager, task=code.id, accept=True, feedback="Good")
    await org.call("report_task", org.worker, task=docs.id, summary="Docs ok")
    await org.call("review_task", org.manager, task=docs.id, accept=True, feedback="Good")
    await org.call("report_task", org.manager, task=root.id, summary="Login works")

    [to_ceo] = await _pending(org, org.ceo)
    assert (to_ceo.source, to_ceo.task_id) == (WakeupSource.CHILD_REPORT, root.id)
    assert await _prompt(org, to_ceo) == (
        f'Task #{root.id} "Ship login" reported: ready for review. Read it with task_overview.'
    )
    assert "Login works" in await org.call("task_overview", org.ceo, task=root.id)
    assert len(await _pending(org, org.manager)) == 1
