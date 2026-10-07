"""The downstream side of an order: receive it, hand it to the CEO verbatim, queue reports.

The CEO receives the upstream's words as a wakeup of its own source, `upstream_order`. That
source is not `owner_message`, so `owner_message_of_run` never returns an upstream order and
the upstream can never close a root task by quoting the owner (the CEO's `owner_decision`).
"""

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.enums import ReportKind, WakeupSource
from labhq.db.models import FederationInbound, FederationReport, Task, WakeupRequest
from labhq.federation.errors import FederationError
from labhq.hierarchy import find_ceo
from labhq.scheduler import Outcome, Wakeup, enqueue
from labhq.scheduler.sources import InvalidWakeupError, default_sources

BUDGET_SUMMARY = "This instance's CEO has no budget left to take the order."
SUMMARY_CHARS = 500


@dataclass(frozen=True)
class Received:
    inbound: FederationInbound
    # False when this order had been received before: nothing was queued again.
    new: bool


class UpstreamOrderHandler:
    """Briefs the CEO with the upstream's order exactly as written, under one header line."""

    def validate(self, task_id: int | None) -> None:
        if task_id is not None:
            raise InvalidWakeupError("upstream orders do not belong to a task")

    def prompt(self, request: WakeupRequest, task: Task | None) -> str:
        data = json.loads(request.reason)
        return (
            f"Order {data['inbound']} from upstream {data['upstream']}. Its words, unchanged:\n\n"
            f"{data['text']}"
        )


default_sources.register(WakeupSource.UPSTREAM_ORDER, UpstreamOrderHandler(), replace=True)


async def receive_order(
    db: AsyncSession,
    clock: Clock,
    *,
    upstream_name: str,
    upstream_order_id: int,
    text: str,
    spend_cap_micros: int | None,
) -> Received:
    """Store an order and wake the CEO with it. The caller commits."""
    existing = await db.scalar(
        select(FederationInbound).where(FederationInbound.upstream_order_id == upstream_order_id)
    )
    if existing is not None:
        return Received(existing, new=False)
    ceo = await find_ceo(db)
    if ceo is None:
        raise FederationError("this instance has no CEO to take the order")
    now = clock.now()
    inbound = FederationInbound(
        upstream_order_id=upstream_order_id,
        upstream_name=upstream_name,
        text=text,
        spend_cap_micros=spend_cap_micros,
        task_ids=[],
        received_at=now,
    )
    db.add(inbound)
    await db.flush()
    reason = json.dumps(
        {"inbound": inbound.id, "upstream": upstream_name, "text": text}, ensure_ascii=False
    )
    result = await enqueue(
        db,
        Wakeup(
            agent_id=ceo.id,
            source=WakeupSource.UPSTREAM_ORDER,
            idempotency_key=f"upstream-order:{inbound.id}",
            reason=reason,
        ),
        clock,
    )
    if result.outcome is Outcome.REFUSED:
        add_report(db, clock, inbound, ReportKind.BLOCKED, BUDGET_SUMMARY, "")
    return Received(inbound, new=True)


def add_report(
    db: AsyncSession,
    clock: Clock,
    inbound: FederationInbound,
    status: ReportKind,
    summary: str,
    ref: str,
) -> FederationReport:
    inbound.report_seq += 1
    report = FederationReport(
        inbound_id=inbound.id,
        seq=inbound.report_seq,
        status=status,
        summary=summary[:SUMMARY_CHARS],
        ref=ref,
        created_at=clock.now(),
    )
    db.add(report)
    return report


async def find_inbound(db: AsyncSession, inbound_id: int) -> FederationInbound:
    inbound = await db.get(FederationInbound, inbound_id)
    if inbound is None:
        raise FederationError(f"no upstream order {inbound_id}")
    return inbound
