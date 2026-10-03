"""Managers and leads create and assign tasks inside their own scope only."""

from labhq.db.enums import TaskStatus, WakeupSource, WakeupStatus
from labhq.db.models import Task
from tests.roles.conftest import Org


async def test_a_manager_creates_a_task_in_its_project_for_its_team(org: Org) -> None:
    answer = await org.call("create_task", org.manager, title="Signup", assignee=org.worker)

    [task] = [task for task in await org.all(Task) if task.title == "Signup"]
    assert (task.project_id, task.assignee_id) == (org.site, org.worker)
    assert answer == f"Task #{task.id} created, assigned to agent {org.worker}."
    [wakeup] = await org.wakeups()
    assert (wakeup.agent_id, wakeup.task_id) == (org.worker, task.id)
    assert wakeup.source is WakeupSource.ASSIGNMENT
    assert "Site manager" in wakeup.reason


async def test_a_manager_assigns_a_task_of_its_project(org: Org) -> None:
    answer = await org.call("assign_task", org.manager, task=org.site_task, agent=org.other_worker)

    task = await org.get(Task, org.site_task)
    assert task.assignee_id == org.other_worker
    assert answer.startswith(f"Task #{org.site_task} assigned to agent {org.other_worker}")
    [wakeup] = await org.wakeups()
    assert (wakeup.agent_id, wakeup.status) == (org.other_worker, WakeupStatus.PENDING)


async def test_a_manager_cannot_act_on_another_project(org: Org) -> None:
    on_their_task = await org.call("assign_task", org.manager, task=org.shop_task, agent=org.worker)
    to_their_agent = await org.call(
        "assign_task", org.manager, task=org.site_task, agent=org.shop_worker
    )
    creating_for_them = await org.call(
        "create_task", org.manager, title="Coupons", assignee=org.shop_worker
    )
    naming_their_project = await org.call(
        "create_task", org.manager, title="Coupons", project="shop"
    )

    assert on_their_task == f"Refused: task {org.shop_task} is not in your project"
    assert to_their_agent == f"Refused: agent {org.shop_worker} is not in your team"
    assert creating_for_them == f"Refused: agent {org.shop_worker} is not in your team"
    assert naming_their_project.startswith("Invalid arguments")
    assert (await org.get(Task, org.shop_task)).assignee_id is None
    assert [task.title for task in await org.all(Task)] == ["Login", "Cart"]
    assert await org.wakeups() == []


async def test_a_lead_assigns_inside_its_team(org: Org) -> None:
    answer = await org.call("assign_task", org.lead, task=org.site_task, agent=org.worker)
    assert answer.startswith(f"Task #{org.site_task} assigned to agent {org.worker}")
    [wakeup] = await org.wakeups()
    assert wakeup.agent_id == org.worker


async def test_a_lead_cannot_assign_outside_its_team(org: Org) -> None:
    sibling = await org.call("assign_task", org.lead, task=org.site_task, agent=org.other_worker)
    upward = await org.call("assign_task", org.lead, task=org.site_task, agent=org.manager)
    created = await org.call("create_task", org.lead, title="Logo", assignee=org.other_worker)
    unknown = await org.call("assign_task", org.lead, task=org.site_task, agent=9999)

    assert sibling == f"Refused: agent {org.other_worker} is not in your team"
    assert upward == f"Refused: agent {org.manager} is not in your team"
    assert created == f"Refused: agent {org.other_worker} is not in your team"
    assert unknown == "Refused: no agent 9999"
    assert (await org.get(Task, org.site_task)).assignee_id is None
    assert await org.wakeups() == []


async def test_a_closed_task_is_not_reassigned(org: Org) -> None:
    async with org.sessions() as db:
        task = await db.get_one(Task, org.site_task)
        task.status = TaskStatus.DONE
        await db.commit()
    answer = await org.call("assign_task", org.lead, task=org.site_task, agent=org.worker)
    assert answer == f"Refused: task {org.site_task} is done"
