"""The upstream's half of the A2A transport: send queued orders, read the tasks back.

One `sync_once` is one round for every active node that has an A2A URL, and is safe to
repeat: an order is sent once (its task id is kept), and a report applies once (the
sequence number, as in polling). A node that fails does not stop the others; the failure is
reported and the next round retries it. Polling nodes are untouched.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from a2a.types import Artifact, Task, TaskState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db.enums import OrderStage, ReportKind
from labhq.db.models import FederationNode, FederationOrder
from labhq.federation.a2a.client import NodeA2aClient
from labhq.federation.a2a.states import (
    REPORT_REF,
    REPORT_SEQ,
    REPORT_STATUS,
    TERMINAL_STATES,
)
from labhq.federation.errors import FederationError
from labhq.federation.orders import receive_report
from labhq.federation.settings import FederationSettings

# Builds the client for a node. Tests swap the transport; the default dials the network.
ClientFactoryFn = Callable[[FederationNode, str], NodeA2aClient]


@dataclass
class SyncResult:
    orders_sent: int = 0
    reports_applied: int = 0
    # node name -> why this round could not finish for it.
    failures: dict[str, str] = field(default_factory=dict)


def default_client(settings: FederationSettings) -> ClientFactoryFn:
    def make(node: FederationNode, key: str) -> NodeA2aClient:
        assert node.a2a_url is not None
        return NodeA2aClient(node.a2a_url, key, timeout=settings.request_timeout_seconds)

    return make


def node_key(settings: FederationSettings, node: FederationNode) -> str:
    secret = settings.node_keys.get(node.name)
    if secret is None:
        raise FederationError(
            f"set LABHQ_FEDERATION_NODE_KEYS to include a key for node {node.name!r}"
        )
    return secret.get_secret_value()


async def a2a_nodes(db: AsyncSession) -> list[FederationNode]:
    return list(
        await db.scalars(
            select(FederationNode)
            .where(FederationNode.a2a_url.is_not(None), FederationNode.revoked_at.is_(None))
            .order_by(FederationNode.id)
        )
    )


async def send_pending(
    db: AsyncSession, clock: Clock, node: FederationNode, client: NodeA2aClient
) -> int:
    """Send every order the node has not been given. The node's task id is kept at once."""
    orders = list(
        await db.scalars(
            select(FederationOrder)
            .where(
                FederationOrder.node_id == node.id,
                FederationOrder.status == OrderStage.PENDING,
            )
            .order_by(FederationOrder.id)
        )
    )
    for order in orders:
        task = await client.send_order(order.id, order.text, order.spend_cap_micros)
        now = clock.now()
        order.remote_task_id = task.id
        order.remote_state = TaskState.Name(task.status.state)
        # The node stored the order before answering: delivered and acknowledged in one step.
        order.status = OrderStage.ACKNOWLEDGED
        order.delivered_at = order.acknowledged_at = now
        await db.commit()
    return len(orders)


def _report_of(artifact: Artifact) -> tuple[int, ReportKind, str, str] | None:
    """The (seq, status, summary, ref) a report artifact carries, if it is one of ours."""
    fields = dict(artifact.metadata.items())
    seq, status = fields.get(REPORT_SEQ), fields.get(REPORT_STATUS)
    if not isinstance(seq, int | float) or not isinstance(status, str):
        return None
    summary = "".join(part.text for part in artifact.parts)
    ref = str(fields.get(REPORT_REF, ""))
    try:
        kind = ReportKind(status)
    except ValueError:
        return None
    return int(seq), kind, summary, ref


async def apply_task(
    db: AsyncSession, clock: Clock, node: FederationNode, order: FederationOrder, task: Task
) -> int:
    """Apply the task's reports the order has not seen, oldest first. Returns how many."""
    applied = 0
    reports = sorted(filter(None, map(_report_of, task.artifacts)), key=lambda report: report[0])
    for seq, status, summary, ref in reports:
        if await receive_report(
            db,
            clock,
            node,
            order_id=order.id,
            seq=seq,
            status=status,
            summary=summary,
            ref=ref,
        ):
            applied += 1
    order.remote_state = TaskState.Name(task.status.state)
    return applied


async def pull_reports(
    db: AsyncSession, clock: Clock, node: FederationNode, client: NodeA2aClient
) -> int:
    """Read the task of every order the node may still report on."""
    open_orders = list(
        await db.scalars(
            select(FederationOrder)
            .where(
                FederationOrder.node_id == node.id,
                FederationOrder.remote_task_id.is_not(None),
                FederationOrder.remote_state.not_in(
                    [TaskState.Name(state) for state in TERMINAL_STATES]
                ),
            )
            .order_by(FederationOrder.id)
        )
    )
    applied = 0
    for order in open_orders:
        assert order.remote_task_id is not None
        task = await client.get_task(order.remote_task_id)
        applied += await apply_task(db, clock, node, order, task)
        await db.commit()
    return applied


async def sync_once(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    settings: FederationSettings,
    *,
    make_client: ClientFactoryFn | None = None,
) -> SyncResult:
    result = SyncResult()
    make = make_client or default_client(settings)
    async with sessions() as db:
        nodes = await a2a_nodes(db)
    for node in nodes:
        try:
            async with make(node, node_key(settings, node)) as client, sessions() as db:
                live = await db.get_one(FederationNode, node.id)
                result.orders_sent += await send_pending(db, clock, live, client)
                result.reports_applied += await pull_reports(db, clock, live, client)
        except (FederationError, httpx.HTTPError) as error:
            result.failures[node.name] = str(error)
    return result
