"""`brief`: what was delivered, what needs the owner, and today's spend.

Results, not activity (plan §8.2): nothing here says what agents are doing right now.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers.pending import count_pending
from labhq.callcenter.answers.phrasing import clean, name_list, since_phrase
from labhq.clock import Clock, ensure_utc
from labhq.db.enums import ApprovalStatus, RunStatus
from labhq.db.models import Approval, CostEvent, Run, Task
from labhq.speech import join_sentences, say_count, say_micros, speakable

LISTED_TITLES = 3
_APPROVED = (ApprovalStatus.APPROVED, ApprovalStatus.EXECUTED)


async def _finished_titles(db: AsyncSession, since: datetime) -> tuple[list[str], int]:
    on_window = (Run.status == RunStatus.SUCCEEDED, Run.finished_at >= since)
    total = await db.scalar(
        select(func.count(func.distinct(Run.task_id))).where(*on_window, Run.task_id.is_not(None))
    )
    rows = await db.execute(
        select(Task.title)
        .join(Run, Run.task_id == Task.id)
        .where(*on_window)
        .group_by(Task.id, Task.title)
        .order_by(func.max(Run.finished_at).desc(), Task.id)
        .limit(LISTED_TITLES)
    )
    return [clean(title) for (title,) in rows.all()], total or 0


async def _approved_titles(db: AsyncSession, since: datetime) -> tuple[list[str], int]:
    on_window = (Approval.status.in_(_APPROVED), Approval.decided_at >= since)
    total = await db.scalar(select(func.count()).select_from(Approval).where(*on_window))
    rows = await db.execute(
        select(Approval.type, Task.title)
        .outerjoin(Task, Task.id == Approval.task_id)
        .where(*on_window)
        .order_by(Approval.decided_at.desc(), Approval.id)
        .limit(LISTED_TITLES)
    )
    phrases = [
        f"{clean(kind)} for {clean(title)}" if title else clean(kind) for kind, title in rows.all()
    ]
    return phrases, total or 0


async def _spend_today(db: AsyncSession, clock: Clock) -> int:
    now = clock.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total = await db.scalar(
        select(func.coalesce(func.sum(CostEvent.cost_micros), 0)).where(
            CostEvent.created_at >= midnight
        )
    )
    return int(total or 0)


async def brief(db: AsyncSession, clock: Clock, since: datetime | None = None) -> str:
    now = clock.now()
    window_start = (
        ensure_utc(since) if since else now.replace(hour=0, minute=0, second=0, microsecond=0)
    )
    window = since_phrase(since, clock)
    parts: list[str] = []

    finished, finished_total = await _finished_titles(db, window_start)
    approved, approved_total = await _approved_titles(db, window_start)
    if finished_total:
        parts.append(
            f"{say_count(finished_total, 'task').capitalize()} finished {window}: "
            f"{name_list(finished, finished_total)}"
        )
    if approved_total:
        parts.append(
            f"{say_count(approved_total, 'approval').capitalize()} went through {window}: "
            f"{name_list(approved, approved_total)}"
        )
    if not parts:
        parts.append(f"Nothing was delivered {window}")

    approvals, questions = await count_pending(db)
    if approvals + questions:
        parts.append(
            f"Waiting on you: {say_count(approvals, 'approval')} "
            f"and {say_count(questions, 'question')}. Ask for your inbox to hear them"
        )
    else:
        parts.append("Nothing is waiting on you")

    parts.append(f"Today's spend is {say_micros(await _spend_today(db, clock))}")
    return speakable(join_sentences(parts))
