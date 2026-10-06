"""Task handoffs travel up the reporting tree; rejected work travels back down."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.ceoreports import record_report
from labhq.clock import Clock
from labhq.db.enums import TaskStatus, WakeupSource
from labhq.db.models import Agent, Comment, Department, Task
from labhq.hierarchy.roles import CEO
from labhq.scheduler import Wakeup, enqueue
from labhq.work.deliverables import default_deliverables, has_document
from labhq.work.service import WorkError

CLOSED = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})


async def reviewer(db: AsyncSession, task: Task) -> tuple[int, int]:
    """Return reviewer agent and the task that should wake it."""
    if task.parent_id is not None:
        parent = await db.get_one(Task, task.parent_id)
        if parent.assignee_id is not None:
            return parent.assignee_id, parent.id
    if task.assignee_id is None:
        raise WorkError(f"task {task.id} has no assignee")
    assignee = await db.get_one(Agent, task.assignee_id)
    if assignee.reports_to is None:
        raise WorkError(f"task {task.id} has no reviewer")
    return assignee.reports_to, task.id


async def _record(
    db: AsyncSession, clock: Clock, task: Task, agent_id: int | None, text: str
) -> Comment:
    comment = Comment(
        task_id=task.id,
        author_agent_id=agent_id,
        body=text,
        mentions=[],
        created_at=clock.now(),
    )
    db.add(comment)
    await db.flush()
    return comment


async def _wake(
    db: AsyncSession, clock: Clock, *, agent_id: int, task_id: int, comment: Comment
) -> None:
    result = await enqueue(
        db,
        Wakeup(
            agent_id=agent_id,
            source=WakeupSource.COMMENT,
            idempotency_key=f"task-progress:comment:{comment.id}:agent:{agent_id}",
            task_id=task_id,
            reason=f"Task #{comment.task_id} changed. Read it and continue the objective.",
        ),
        clock,
    )
    # Coalescing keeps the earlier wakeup but drops this reason unless we append it.
    if result.outcome.value == "coalesced":
        result.request.reason += f"\nTask #{comment.task_id} changed."


async def _check_deliverable(db: AsyncSession, task: Task) -> None:
    """A task that owes a document cannot be reported ready before the file exists."""
    if not default_deliverables.get(task.deliverable).needs_document:
        return
    department = await db.get(Department, task.department_id) if task.department_id else None
    if department is None or not has_document(Path(department.folder), task.deliverable_ref):
        raise WorkError(f"task {task.id} delivers a document: save it with `write_document` first")


async def report_task(
    db: AsyncSession, clock: Clock, task: Task, agent_id: int, *, summary: str, blocked: bool
) -> None:
    if task.assignee_id != agent_id:
        raise WorkError(f"task {task.id} is not assigned to you")
    if task.status in CLOSED:
        raise WorkError(f"task {task.id} is {task.status}")
    if not blocked:
        unfinished = await db.scalar(
            select(Task.id).where(Task.parent_id == task.id, Task.status.not_in(CLOSED)).limit(1)
        )
        if unfinished is not None:
            raise WorkError(f"task {task.id} still has unfinished child task {unfinished}")
    if not blocked:
        await _check_deliverable(db, task)
    reviewer_id, wake_task_id = await reviewer(db, task)
    task.status = TaskStatus.BLOCKED if blocked else TaskStatus.IN_REVIEW
    task.updated_at = clock.now()
    if task.parent_id is not None:
        parent = await db.get_one(Task, task.parent_id)
        parent.updated_at = clock.now()
    comment = await _record(db, clock, task, agent_id, summary)
    await _wake(db, clock, agent_id=reviewer_id, task_id=wake_task_id, comment=comment)


async def review_task(
    db: AsyncSession, clock: Clock, task: Task, agent_id: int, *, accept: bool, feedback: str
) -> None:
    reviewer_id, _ = await reviewer(db, task)
    if agent_id != reviewer_id:
        raise WorkError(f"task {task.id} is not yours to review")
    if task.status not in {TaskStatus.IN_REVIEW, TaskStatus.BLOCKED}:
        raise WorkError(f"task {task.id} is {task.status}, not awaiting review")
    if accept and task.status is TaskStatus.BLOCKED:
        raise WorkError(f"blocked task {task.id} cannot be accepted")
    reviewer_agent = await db.get_one(Agent, agent_id)
    # The CEO can recommend acceptance, but the owner alone closes a root project objective.
    # A department's root task is the CEO's to close: it runs departments unasked.
    owner_decides = (
        reviewer_agent.role == CEO and task.parent_id is None and task.department_id is None
    )
    if not (accept and owner_decides):
        task.status = TaskStatus.DONE if accept else TaskStatus.TODO
    task.updated_at = clock.now()
    if task.parent_id is not None:
        parent = await db.get_one(Task, task.parent_id)
        parent.updated_at = clock.now()
    comment = await _record(db, clock, task, agent_id, feedback)
    if accept and owner_decides:
        # The owner accepts or returns it from the report in the CEO chat.
        await record_report(
            db,
            clock,
            agent_id=agent_id,
            text=f"T{task.id} {task.title} is done and waits for your decision.\n{feedback}",
            refs=[f"T{task.id}"],
            task_id=task.id,
        )
    if accept and reviewer_agent.role == CEO and task.department_id is not None:
        await _report_department_result(db, clock, task, agent_id, feedback)
    if not accept:
        assert task.assignee_id is not None
        await _wake(db, clock, agent_id=task.assignee_id, task_id=task.id, comment=comment)


async def _report_department_result(
    db: AsyncSession, clock: Clock, task: Task, agent_id: int, feedback: str
) -> None:
    """Tell the owner what a department delivered: the Call Center answers status from it."""
    department = await db.get_one(Department, task.department_id)
    delivered = await db.scalar(
        select(Comment.body)
        .where(Comment.task_id == task.id, Comment.author_agent_id == task.assignee_id)
        .order_by(Comment.id.desc())
        .limit(1)
    )
    where = f" ({task.deliverable_ref})" if task.deliverable_ref else ""
    await record_report(
        db,
        clock,
        agent_id=agent_id,
        text=(
            f"{department.name} delivered T{task.id} {task.title}, a {task.deliverable}"
            f"{where}.\n{delivered or feedback}"
        ),
        refs=[f"T{task.id}", department.name],
        task_id=task.id,
    )


async def owner_decide(
    db: AsyncSession, clock: Clock, task: Task, *, accept: bool, feedback: str
) -> None:
    """The operator's final decision on a root objective."""
    if task.parent_id is not None:
        raise WorkError(f"task {task.id} is a subtask; decide on its root objective")
    if task.status not in {TaskStatus.IN_REVIEW, TaskStatus.BLOCKED}:
        raise WorkError(f"task {task.id} is {task.status}, not awaiting a decision")
    if accept and task.status is TaskStatus.BLOCKED:
        raise WorkError(f"blocked task {task.id} cannot be accepted")
    task.status = TaskStatus.DONE if accept else TaskStatus.TODO
    task.updated_at = clock.now()
    comment = await _record(db, clock, task, None, feedback)
    if not accept:
        if task.assignee_id is None:
            raise WorkError(f"task {task.id} has no assignee to revise it")
        await _wake(db, clock, agent_id=task.assignee_id, task_id=task.id, comment=comment)
