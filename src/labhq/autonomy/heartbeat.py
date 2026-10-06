"""The global CEO's heartbeat: one timer wakeup per period, briefed from data.

The brief lists only what changed since the CEO's last turn, so a quiet organisation costs
a few words, not a prompt. The idempotency key carries the period, so a retried or doubled
pass never wakes the CEO twice.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.autonomy.settings import Autonomy, AutonomySettings, get_autonomy_settings
from labhq.autonomy.state import get_autonomy
from labhq.ceosessions import CEO_ROLE
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, ApprovalStatus, TaskStatus, WakeupSource
from labhq.db.models import Agent, Approval, BudgetWarning, Comment, Run, Task
from labhq.scheduler import EnqueueResult, Outcome, Wakeup

type Enqueue = Callable[[Wakeup], Awaitable[EnqueueResult]]

# A long backlog is a reason to open the task list, not to paste it into a prompt.
LIST_LIMIT = 10
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NOTHING_NEW = "Nothing changed since your last turn."
HANDOFF_STATUSES = frozenset({TaskStatus.IN_REVIEW, TaskStatus.BLOCKED})


@dataclass
class Brief:
    reports: list[str] = field(default_factory=list)
    stalled: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    budgets: list[str] = field(default_factory=list)

    def text(self) -> str:
        sections = [
            ("New reports", self.reports),
            ("Stalled tasks", self.stalled),
            ("Open approvals", self.approvals),
            ("Budget warnings", self.budgets),
        ]
        lines = [f"{title}:\n" + "\n".join(items) for title, items in sections if items]
        return "\n".join(lines) or NOTHING_NEW


def _capped(items: list[str]) -> list[str]:
    extra = len(items) - LIST_LIMIT
    return items[:LIST_LIMIT] + ([f"- and {extra} more"] if extra > 0 else [])


async def last_turn(db: AsyncSession, agent_id: int) -> datetime | None:
    return await db.scalar(select(func.max(Run.created_at)).where(Run.agent_id == agent_id))


async def build_brief(
    db: AsyncSession, agent_id: int, *, since: datetime | None, now: datetime, stall_after: int
) -> Brief:
    floor = since or EPOCH
    brief = Brief()
    reports = await db.execute(
        select(Task.id, Task.title, Task.status)
        .join(Comment, Comment.task_id == Task.id)
        .where(
            Comment.created_at > floor,
            Comment.author_agent_id.is_not(None),
            Comment.author_agent_id != agent_id,
            Task.status.in_(HANDOFF_STATUSES),
        )
        .distinct()
        .order_by(Task.id)
    )
    brief.reports = _capped([f"- T{row.id} {row.title} ({row.status})" for row in reports])

    # A task stalls when a full period passes without a change; it is listed once, in the
    # heartbeat whose window contains that moment.
    period = timedelta(seconds=stall_after)
    stalled = await db.execute(
        select(Task.id, Task.title)
        .where(
            Task.status == TaskStatus.IN_PROGRESS,
            Task.updated_at <= now - period,
            Task.updated_at > floor - period,
        )
        .order_by(Task.id)
    )
    brief.stalled = _capped([f"- T{row.id} {row.title}" for row in stalled])

    approvals = await db.execute(
        select(Approval.id, Approval.type, Approval.risk_class)
        .where(Approval.status == ApprovalStatus.PENDING, Approval.created_at > floor)
        .order_by(Approval.id)
    )
    brief.approvals = _capped([f"- A{row.id} {row.type} ({row.risk_class})" for row in approvals])

    warnings = await db.execute(
        select(BudgetWarning.scope, BudgetWarning.scope_id)
        .where(BudgetWarning.created_at > floor)
        .order_by(BudgetWarning.id)
    )
    brief.budgets = _capped(
        [f"- {row.scope} {row.scope_id} is near its budget" for row in warnings]
    )
    return brief


async def heartbeat_pass(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    enqueue: Enqueue,
    settings: AutonomySettings | None = None,
) -> list[int]:
    """Wake each active global CEO once for the current period; return their agent ids."""
    settings = settings or get_autonomy_settings()
    interval = settings.ceo_heartbeat_seconds
    if interval == 0:
        return []
    now = clock.now()
    async with sessions() as db:
        if await get_autonomy(db, settings) is Autonomy.PAUSED:
            return []
        ceos = list(
            await db.scalars(
                select(Agent.id)
                .where(
                    Agent.role == CEO_ROLE,
                    Agent.project_id.is_(None),
                    Agent.status == AgentStatus.ACTIVE,
                )
                .order_by(Agent.id)
            )
        )
        briefs = {
            ceo: await build_brief(
                db, ceo, since=await last_turn(db, ceo), now=now, stall_after=interval
            )
            for ceo in ceos
        }
    period = int(now.timestamp()) // interval
    woken = []
    for ceo, brief in briefs.items():
        result = await enqueue(
            Wakeup(
                agent_id=ceo,
                source=WakeupSource.TIMER,
                idempotency_key=f"ceo-heartbeat:{ceo}:{period}",
                reason=brief.text(),
            )
        )
        if result.outcome is Outcome.CREATED:
            woken.append(ceo)
    return woken
