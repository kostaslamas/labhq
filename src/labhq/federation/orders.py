"""The upstream side of an order: queue it, hand it to the node, take its reports back.

An order is the words of a task given to a remote manager, stored once and delivered
unchanged. Reports come back as pointers (a status and a reference on the node) and land as
ordinary task reports by the remote manager, so `task_overview`, the review wakeup and the
Call Center's status answers need nothing new.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.enums import OrderStatus, UpstreamStatus
from labhq.db.models import Agent, Comment, FederationNode, FederationOrder, Run, Task
from labhq.federation.errors import FederationError
from labhq.federation.nodes import NODE_CONFIG_KEY
from labhq.work import WorkError
from labhq.work.progress import report_task

RETURNED_HEADER = "The task was returned with this feedback:"


def order_words(task: Task) -> str:
    """The task as its giver wrote it: title, then description if there is one."""
    return f"{task.title}\n\n{task.description}" if task.description.strip() else task.title


async def _returned_words(db: AsyncSession, task: Task, manager_id: int) -> str | None:
    """The feedback that sent a task back, for a task the node already received once."""
    feedback = await db.scalar(
        select(Comment.body)
        .where(Comment.task_id == task.id, Comment.author_agent_id != manager_id)
        .order_by(Comment.id.desc())
        .limit(1)
    )
    return f"{RETURNED_HEADER}\n{feedback}" if feedback else None


async def queue_order(db: AsyncSession, clock: Clock, run_id: int) -> FederationOrder:
    """Queue the order a remote manager's run stands for. The caller commits.

    The run id makes this idempotent: a retried run finds its order and queues nothing twice.
    """
    existing = await db.scalar(select(FederationOrder).where(FederationOrder.run_id == run_id))
    if existing is not None:
        return existing
    run = await db.get(Run, run_id)
    if run is None or run.task_id is None:
        raise FederationError("a remote manager takes tasks only; this run has none")
    manager = await db.get_one(Agent, run.agent_id)
    node_id = manager.config.get(NODE_CONFIG_KEY)
    node = await db.get(FederationNode, node_id) if isinstance(node_id, int) else None
    if node is None:
        raise FederationError(f"agent {manager.id} is not the manager of a federation node")
    if node.revoked_at is not None:
        raise FederationError(f"node {node.name!r} is revoked")
    task = await db.get_one(Task, run.task_id)
    earlier = await db.scalar(
        select(FederationOrder.id).where(FederationOrder.task_id == task.id).limit(1)
    )
    text = (await _returned_words(db, task, manager.id)) if earlier else None
    order = FederationOrder(
        node_id=node.id,
        task_id=task.id,
        run_id=run_id,
        text=text or order_words(task),
        spend_cap_micros=node.spend_cap_micros,
        created_at=clock.now(),
    )
    db.add(order)
    await db.flush()
    return order


async def fetch_pending(
    db: AsyncSession, clock: Clock, node: FederationNode
) -> list[FederationOrder]:
    """Orders the node has not acknowledged, oldest first. The caller commits."""
    orders = list(
        await db.scalars(
            select(FederationOrder)
            .where(
                FederationOrder.node_id == node.id,
                FederationOrder.status != OrderStatus.ACKNOWLEDGED,
            )
            .order_by(FederationOrder.id)
        )
    )
    now = clock.now()
    for order in orders:
        if order.status is OrderStatus.PENDING:
            order.status = OrderStatus.DELIVERED
            order.delivered_at = now
    return orders


async def _own_order(db: AsyncSession, node: FederationNode, order_id: int) -> FederationOrder:
    order = await db.get(FederationOrder, order_id)
    # Another node's order is "not found" to this one, not "forbidden".
    if order is None or order.node_id != node.id:
        raise FederationError(f"no order {order_id}")
    return order


async def acknowledge(
    db: AsyncSession, clock: Clock, node: FederationNode, order_id: int
) -> FederationOrder:
    order = await _own_order(db, node, order_id)
    if order.status is not OrderStatus.ACKNOWLEDGED:
        order.status = OrderStatus.ACKNOWLEDGED
        order.acknowledged_at = clock.now()
        order.delivered_at = order.delivered_at or order.acknowledged_at
    return order


def report_body(node: FederationNode, summary: str, ref: str) -> str:
    where = f" (see {ref} on {node.name})" if ref else ""
    return f"{node.name}: {summary}{where}"


async def receive_report(
    db: AsyncSession,
    clock: Clock,
    node: FederationNode,
    *,
    order_id: int,
    seq: int,
    status: UpstreamStatus,
    summary: str,
    ref: str,
) -> bool:
    """Apply a node's report to the order's task. False when `seq` was already applied."""
    order = await _own_order(db, node, order_id)
    if seq <= order.report_seq:
        return False
    if order.task_id is None or node.manager_agent_id is None:
        raise FederationError(f"order {order_id} no longer has a task to report on")
    task = await db.get_one(Task, order.task_id)
    body = report_body(node, summary, ref)
    try:
        if status is UpstreamStatus.PROGRESS:
            db.add(
                Comment(
                    task_id=task.id,
                    author_agent_id=node.manager_agent_id,
                    body=body,
                    mentions=[],
                    created_at=clock.now(),
                )
            )
        else:
            await report_task(
                db,
                clock,
                task,
                node.manager_agent_id,
                summary=body,
                blocked=status is UpstreamStatus.BLOCKED,
            )
    except WorkError as error:
        raise FederationError(str(error)) from None
    order.report_seq = seq
    return True
