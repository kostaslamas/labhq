"""The per-order spend cap, enforced where the work runs.

The scheduler calls `refuse_over_cap` before it starts a run. It imports nothing but the
database layer, because `labhq.scheduler` imports this module.

An order's spend is what the runs on its delegated tasks, and on every task below them,
cost. The CEO's own turns are not counted: the CEO is shared with the owner's work.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.enums import ReportKind
from labhq.db.models import CostEvent, FederationInbound, FederationReport, Run, Task

CAP_SUMMARY = "Spend cap reached on this instance; no more work is started for this order."


async def _root_of(db: AsyncSession, task_id: int) -> int:
    seen = {task_id}
    current = task_id
    while True:
        parent_id = await db.scalar(select(Task.parent_id).where(Task.id == current))
        if parent_id is None or parent_id in seen:
            return current
        seen.add(parent_id)
        current = parent_id


async def _subtree(db: AsyncSession, roots: list[int]) -> set[int]:
    found = set(roots)
    frontier = list(roots)
    while frontier:
        children = await db.scalars(select(Task.id).where(Task.parent_id.in_(frontier)))
        frontier = [child for child in children if child not in found]
        found.update(frontier)
    return found


async def order_spend_micros(db: AsyncSession, order: FederationInbound) -> int:
    tasks = await _subtree(db, [int(task_id) for task_id in order.task_ids])
    total = await db.scalar(
        select(func.coalesce(func.sum(CostEvent.cost_micros), 0))
        .join(Run, Run.id == CostEvent.run_id)
        .where(Run.task_id.in_(tasks))
    )
    return int(total or 0)


async def order_of_task(db: AsyncSession, task_id: int) -> FederationInbound | None:
    """The capped order a task belongs to, if any."""
    root = await _root_of(db, task_id)
    capped = await db.scalars(
        select(FederationInbound).where(FederationInbound.spend_cap_micros.is_not(None))
    )
    return next((order for order in capped if root in order.task_ids), None)


async def over_cap(db: AsyncSession, order: FederationInbound) -> bool:
    cap = order.spend_cap_micros
    return cap is not None and await order_spend_micros(db, order) >= cap


async def refuse_over_cap(db: AsyncSession, clock: Clock, task_id: int) -> bool:
    """True when `task_id` belongs to an order that has spent its cap.

    The first refusal also queues one blocked report, so the upstream sees why its order
    stopped instead of waiting on it.
    """
    order = await order_of_task(db, task_id)
    if order is None or not await over_cap(db, order):
        return False
    last = await db.scalar(
        select(FederationReport)
        .where(FederationReport.inbound_id == order.id)
        .order_by(FederationReport.seq.desc())
        .limit(1)
    )
    if last is None or last.summary != CAP_SUMMARY:
        order.report_seq += 1
        db.add(
            FederationReport(
                inbound_id=order.id,
                seq=order.report_seq,
                status=ReportKind.BLOCKED,
                summary=CAP_SUMMARY,
                ref=f"order {order.upstream_order_id}",
                created_at=clock.now(),
            )
        )
    return True
