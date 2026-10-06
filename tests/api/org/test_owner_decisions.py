"""The owner reads the CEO's reports and decides root tasks over the API, without the CLI."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from labhq.ceoreports import record_report
from labhq.cli.context import Context
from labhq.db.enums import AgentStatus, TaskStatus, WakeupSource
from labhq.db.models import Agent, Comment, Project, Task, WakeupRequest
from tests.auth.conftest import WRITE


async def awaiting_owner(context: Context, title: str = "Ship login") -> tuple[int, int]:
    """A root task the CEO recommended, with its report; returns (task, manager) ids."""
    now = context.clock.now()
    async with context.sessions() as db:
        project = Project(name=f"p-{title}", repo_path="/r", created_at=now, updated_at=now)
        db.add(project)
        await db.flush()
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
        manager = Agent(
            project_id=project.id,
            role="manager",
            title="Manager",
            reports_to=ceo.id,
            adapter="fake",
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add(manager)
        await db.flush()
        task = Task(
            project_id=project.id,
            title=title,
            assignee_id=manager.id,
            status=TaskStatus.IN_REVIEW,
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        await db.flush()
        await record_report(
            db,
            context.clock,
            agent_id=ceo.id,
            text=f"T{task.id} is done.",
            refs=[f"T{task.id}"],
            task_id=task.id,
        )
        await db.commit()
        return task.id, manager.id


async def test_the_owner_accepts_a_reported_root_task(
    signed_in: TestClient, context: Context
) -> None:
    task_id, _ = await awaiting_owner(context)
    (report,) = (signed_in.get("/api/org/ceo/reports")).json()
    assert (report["task_id"], report["task_title"], report["awaiting_decision"]) == (
        task_id,
        "Ship login",
        True,
    )

    response = signed_in.post(f"/api/org/tasks/{task_id}/accept", headers=WRITE, json={})

    assert response.status_code == 200, response.text
    assert response.json() == {"task_id": task_id, "status": "done"}
    (report,) = (signed_in.get("/api/org/ceo/reports")).json()
    assert report["awaiting_decision"] is False
    again = signed_in.post(f"/api/org/tasks/{task_id}/accept", headers=WRITE, json={})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "task_not_awaiting_owner"


async def test_the_owner_returns_a_task_with_feedback_to_its_manager(
    signed_in: TestClient, context: Context
) -> None:
    task_id, manager_id = await awaiting_owner(context)

    empty = signed_in.post(
        f"/api/org/tasks/{task_id}/return", headers=WRITE, json={"feedback": "  "}
    )
    response = signed_in.post(
        f"/api/org/tasks/{task_id}/return",
        headers=WRITE,
        json={"feedback": "Add keyboard support"},
    )

    assert empty.status_code == 422
    assert response.status_code == 200, response.text
    assert response.json() == {"task_id": task_id, "status": "todo"}
    async with context.sessions() as db:
        comment = await db.scalar(select(Comment).where(Comment.task_id == task_id))
        wakeup = await db.scalar(select(WakeupRequest).where(WakeupRequest.task_id == task_id))
    assert comment is not None and comment.body == "Add keyboard support"
    assert wakeup is not None
    assert (wakeup.agent_id, wakeup.source) == (manager_id, WakeupSource.TASK_RETURNED)


async def test_an_unknown_task_is_not_found(signed_in: TestClient) -> None:
    response = signed_in.post("/api/org/tasks/999/accept", headers=WRITE, json={})
    assert response.status_code == 404


async def test_today_opens_with_the_latest_ceo_report(
    signed_in: TestClient, context: Context
) -> None:
    assert (signed_in.get("/api/today")).json()["ceo_report"] is None
    await awaiting_owner(context, "Ship login")
    task_id, _ = await awaiting_owner(context, "Ship search")

    report = (signed_in.get("/api/today")).json()["ceo_report"]

    assert (report["text"], report["task_id"], report["awaiting_decision"]) == (
        f"T{task_id} is done.",
        task_id,
        True,
    )
