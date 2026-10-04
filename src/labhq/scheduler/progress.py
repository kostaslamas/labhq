"""Resume unfinished task work after a turn, or escalate repeated non-delivery."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.enums import RunStatus, TaskStatus, WakeupSource, WakeupStatus
from labhq.db.models import Comment, Run, Task, WakeupRequest
from labhq.notify.outbox import enqueue as notify_owner
from labhq.scheduler.wakeups import Wakeup, enqueue

PARKED = frozenset(
    {TaskStatus.IN_REVIEW, TaskStatus.BLOCKED, TaskStatus.DONE, TaskStatus.CANCELLED}
)
TERMINAL = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.TIMED_OUT})


async def continue_task(
    db: AsyncSession, clock: Clock, run_id: int, *, max_unreported_runs: int
) -> None:
    run = await db.get_one(Run, run_id)
    if run.task_id is None or run.status not in TERMINAL:
        return
    task = await db.get_one(Task, run.task_id)
    if task.assignee_id != run.agent_id:
        await _continue_review(db, clock, run, task, max_unreported_runs)
        return
    if task.status in PARKED:
        return
    children = list(await db.scalars(select(Task.status).where(Task.parent_id == task.id)))
    if any(
        status in {TaskStatus.TODO, TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS}
        for status in children
    ):
        return
    if await _pending(db, run):
        return
    attempts = await _attempts(db, run, task)
    if attempts >= max_unreported_runs:
        from labhq.work.progress import report_task, reviewer
        from labhq.work.service import WorkError

        try:
            await reviewer(db, task)
        except WorkError:
            task.status = TaskStatus.BLOCKED
            task.updated_at = clock.now()
            await notify_owner(
                db,
                kind="task_no_reviewer",
                subject=f"task:{task.id}",
                title=f"Task T{task.id} needs a reviewer",
                body=(
                    f"{task.title}: agent {run.agent_id} ended {attempts} turns without a handoff."
                ),
                idempotency_key=f"task-no-reviewer:task:{task.id}:run:{run.id}",
                now=clock.now(),
            )
            return

        await report_task(
            db,
            clock,
            task,
            run.agent_id,
            summary=(
                f"Run {run.id} ended without a task handoff after {attempts} turns; "
                "a reviewer must decide how to proceed."
            ),
            blocked=True,
        )
        return
    await _retry(
        db,
        clock,
        run,
        task,
        "Your task remains open. Review ready children, report it ready, or report the blocker.",
    )


async def _pending(db: AsyncSession, run: Run) -> bool:
    pending = await db.scalar(
        select(WakeupRequest.id)
        .where(
            WakeupRequest.agent_id == run.agent_id,
            WakeupRequest.task_id == run.task_id,
            WakeupRequest.status == WakeupStatus.PENDING,
        )
        .limit(1)
    )
    return pending is not None


async def _attempts(db: AsyncSession, run: Run, task: Task) -> int:
    attempts = await db.scalar(
        select(func.count(Run.id)).where(
            Run.agent_id == run.agent_id,
            Run.task_id == task.id,
            Run.status.in_(TERMINAL),
            Run.created_at >= task.updated_at,
        )
    )
    return attempts or 0


async def _continue_review(
    db: AsyncSession, clock: Clock, run: Run, task: Task, max_unreported_runs: int
) -> None:
    if task.status not in {TaskStatus.IN_REVIEW, TaskStatus.BLOCKED}:
        return
    from labhq.work.progress import reviewer

    reviewer_id, _ = await reviewer(db, task)
    if reviewer_id != run.agent_id:
        return
    acted = await db.scalar(
        select(Comment.id)
        .where(
            Comment.task_id == task.id,
            Comment.author_agent_id == run.agent_id,
            Comment.created_at >= (run.started_at or run.created_at),
        )
        .limit(1)
    )
    if acted is not None or await _pending(db, run):
        return
    attempts = await _attempts(db, run, task)
    if attempts >= max_unreported_runs:
        await notify_owner(
            db,
            kind="task_review_stalled",
            subject=f"task:{task.id}",
            title=f"Task T{task.id} still needs review",
            body=(
                f"{task.title}: agent {run.agent_id} ended {attempts} review turns "
                "without a decision."
            ),
            idempotency_key=f"task-review-stalled:task:{task.id}:run:{run.id}",
            now=clock.now(),
        )
        return
    await _retry(
        db,
        clock,
        run,
        task,
        "This task still awaits your review. Inspect it and decide, or report a blocker.",
    )


async def _retry(db: AsyncSession, clock: Clock, run: Run, task: Task, reason: str) -> None:
    await enqueue(
        db,
        Wakeup(
            agent_id=run.agent_id,
            source=WakeupSource.COMMENT,
            idempotency_key=f"continue:task:{task.id}:run:{run.id}",
            task_id=task.id,
            reason=reason,
        ),
        clock,
    )
