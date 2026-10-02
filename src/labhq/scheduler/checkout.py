"""Atomic task checkout and the per-agent concurrency gate, each one conditional statement.

A read followed by a write would let two schedulers both see a free slot. Each operation
here is a single statement whose WHERE clause carries the condition, so the database
serialises the race and exactly one writer wins (plan §6, invariants).
"""

from datetime import datetime

from sqlalchemy import func, insert, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.enums import RunStatus
from labhq.db.models import Run, Task

ACTIVE_RUN_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)


async def checkout(session: AsyncSession, task_id: int, run_id: int, now: datetime) -> bool:
    """Lock `task_id` for `run_id`. False when another run holds it."""
    result = await session.execute(
        update(Task)
        .where(Task.id == task_id, Task.checkout_run_id.is_(None))
        .values(checkout_run_id=run_id, updated_at=now)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def release(session: AsyncSession, task_id: int, run_id: int, now: datetime) -> bool:
    """Unlock `task_id` if `run_id` still holds it; never frees another run's lock."""
    result = await session.execute(
        update(Task)
        .where(Task.id == task_id, Task.checkout_run_id == run_id)
        .values(checkout_run_id=None, updated_at=now)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def reserve_run(
    session: AsyncSession,
    *,
    agent_id: int,
    task_id: int | None,
    adapter: str,
    concurrency: int,
    now: datetime,
) -> int | None:
    """Insert a queued run unless the agent already has `concurrency` active runs."""
    active = (
        select(func.count())
        .select_from(Run)
        .where(Run.agent_id == agent_id, Run.status.in_(ACTIVE_RUN_STATUSES))
        .scalar_subquery()
    )
    columns = Run.__table__.c
    values = select(
        literal(agent_id, columns.agent_id.type),
        literal(task_id, columns.task_id.type),
        literal(adapter, columns.adapter.type),
        literal(RunStatus.QUEUED, columns.status.type),
        literal(now, columns.created_at.type),
        # A heartbeat from reservation on lets the reaper close a run that never started.
        literal(now, columns.heartbeat_at.type),
    ).where(active < concurrency)
    statement = (
        insert(Run)
        .from_select(
            ["agent_id", "task_id", "adapter", "status", "created_at", "heartbeat_at"], values
        )
        .returning(Run.id)
    )
    run_id: int | None = await session.scalar(statement)
    return run_id
