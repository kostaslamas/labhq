"""Atomic task checkout: one conditional UPDATE, so a task has at most one active run.

Neither function commits; the caller owns the transaction.
"""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.models import Task


async def checkout(session: AsyncSession, task_id: int, run_id: int) -> bool:
    """Take the task for `run_id`. False when another run already holds it."""
    result = await session.execute(
        update(Task)
        .where(Task.id == task_id, Task.checkout_run_id.is_(None))
        .values(checkout_run_id=run_id)
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def release(session: AsyncSession, run_id: int) -> int:
    """Free every task held by `run_id`; a task another run holds is left alone."""
    result = await session.execute(
        update(Task)
        .where(Task.checkout_run_id == run_id)
        .values(checkout_run_id=None)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount)  # type: ignore[attr-defined]
