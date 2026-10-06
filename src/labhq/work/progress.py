"""Task handoffs travel up the reporting tree; rejected work travels back down."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.ceoreports import record_report
from labhq.clock import Clock
from labhq.db.enums import TaskStatus, WakeupSource
from labhq.db.models import Agent, Comment, Department, Task
from labhq.hierarchy.roles import CEO
from labhq.scheduler import Outcome, Wakeup, enqueue
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


def _merge_line(reason: str, prefix: str, line: str) -> str:
    """Add a pointer line to a pending wakeup's reason: once per subject, in arrival order."""
    lines = reason.splitlines()
    for index, existing in enumerate(lines):
        if existing.startswith(prefix):
            lines[index] = line
            return "\n".join(lines)
    return "\n".join([*lines, line])


async def _wake(
    db: AsyncSession,
    clock: Clock,
    *,
    agent_id: int,
    task_id: int,
    comment: Comment,
    source: WakeupSource,
    prefix: str,
    line: str,
) -> None:
    """Point the agent at a result. The line is the whole prompt; the report text never travels."""
    result = await enqueue(
        db,
        Wakeup(
            agent_id=agent_id,
            source=source,
            idempotency_key=f"task-progress:{source}:{comment.id}:agent:{agent_id}",
            task_id=task_id,
            reason=line,
        ),
        clock,
    )
    # Coalescing keeps the earlier wakeup but drops this reason unless we merge it in.
    if result.outcome is Outcome.COALESCED:
        result.request.reason = _merge_line(result.request.reason, prefix, line)


def _title(task: Task) -> str:
    return " ".join(task.title.split())


async def _wake_reviewer(
    db: AsyncSession,
    clock: Clock,
    task: Task,
    *,
    reviewer_id: int,
    wake_task_id: int,
    comment: Comment,
    blocked: bool,
) -> None:
    subject = "Subtask" if wake_task_id != task.id else "Task"
    state = "blocked" if blocked else "ready for review"
    await _wake(
        db,
        clock,
        agent_id=reviewer_id,
        task_id=wake_task_id,
        comment=comment,
        source=WakeupSource.CHILD_REPORT,
        prefix=f"{subject} #{task.id} ",
        line=(
            f'{subject} #{task.id} "{_title(task)}" reported: {state}. Read it with task_overview.'
        ),
    )


async def _wake_returned(db: AsyncSession, clock: Clock, task: Task, comment: Comment) -> None:
    assert task.assignee_id is not None
    line = f"Task #{task.id} was returned. Read the feedback with task_overview."
    await _wake(
        db,
        clock,
        agent_id=task.assignee_id,
        task_id=task.id,
        comment=comment,
        source=WakeupSource.TASK_RETURNED,
        prefix=f"Task #{task.id} was returned",
        line=line,
    )


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
    await _wake_reviewer(
        db,
        clock,
        task,
        reviewer_id=reviewer_id,
        wake_task_id=wake_task_id,
        comment=comment,
        blocked=blocked,
    )


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
        await _wake_returned(db, clock, task, comment)


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
        await _wake_returned(db, clock, task, comment)
