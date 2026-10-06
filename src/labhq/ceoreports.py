"""The CEO's reports to the owner: kept beside the CEO chat, announced as rate-limited digests.

A report always lands in `ceo_reports`. Its notification goes out at once unless one went out
within `digest_seconds`; then it waits for the end of that window, and every report until then
joins the same pending row, so a burst reaches the owner's phone as one digest.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import cast

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock, ensure_utc
from labhq.db.enums import NotificationStatus, TaskStatus
from labhq.db.models import CeoReport, Notification, Task
from labhq.notify.outbox import enqueue

NOTIFICATION_KIND = "ceo_report"
TITLE_CHARS = 200
ENTRY_CHARS = 600


class CeoReportSettings(BaseSettings):
    """How the CEO's reports reach the owner."""

    model_config = SettingsConfigDict(env_prefix="LABHQ_CEO_REPORTS_", extra="ignore")

    # At most one report notification per window; later reports wait and go out as one digest.
    digest_seconds: int = Field(default=900, ge=0)


@lru_cache(maxsize=1)
def get_ceo_report_settings() -> CeoReportSettings:
    return CeoReportSettings()


@dataclass(frozen=True)
class ReportView:
    id: int
    text: str
    refs: list[str]
    task_id: int | None
    task_title: str | None
    # True while this is the latest report on a root task that still waits for the owner.
    awaiting_decision: bool
    created_at: datetime


async def record_report(
    db: AsyncSession,
    clock: Clock,
    *,
    agent_id: int | None,
    text: str,
    refs: Sequence[str] = (),
    task_id: int | None = None,
    settings: CeoReportSettings | None = None,
) -> CeoReport:
    """Store a report and announce it; the caller commits both together."""
    now = clock.now()
    report = CeoReport(
        agent_id=agent_id, text=text, refs=list(refs), task_id=task_id, created_at=now
    )
    db.add(report)
    await db.flush()
    window = timedelta(seconds=(settings or get_ceo_report_settings()).digest_seconds)
    await _announce(db, report, now, window)
    return report


async def _announce(db: AsyncSession, report: CeoReport, now: datetime, window: timedelta) -> None:
    latest = await db.scalar(
        select(Notification)
        .where(Notification.kind == NOTIFICATION_KIND)
        .order_by(Notification.id.desc())
        .limit(1)
    )
    entry = _entry(report)
    if latest is not None and await _join(db, latest, entry):
        return
    due = None
    if latest is not None:
        last = ensure_utc(latest.sent_at or latest.created_at)
        if last + window > now:
            due = last + window
    row = await enqueue(
        db,
        kind=NOTIFICATION_KIND,
        subject=f"ceo_report:{report.id}",
        title="CEO report",
        body=entry,
        idempotency_key=f"ceo-report:{report.id}",
        click_url=_chat_link(),
        now=now,
    )
    row.next_attempt_at = due


async def _join(db: AsyncSession, pending: Notification, entry: str) -> bool:
    """Append to a digest no dispatcher has claimed yet; False if it is already on its way."""
    if pending.status is not NotificationStatus.PENDING or pending.attempts != 0:
        return False
    first_id = int(pending.subject.rpartition(":")[2])
    count = await db.scalar(select(func.count(CeoReport.id)).where(CeoReport.id >= first_id))
    result = await db.execute(
        update(Notification)
        .where(
            Notification.id == pending.id,
            Notification.status == NotificationStatus.PENDING,
            Notification.attempts == 0,
        )
        .values(
            title=f"CEO: {count} reports"[:TITLE_CHARS],
            body=Notification.body + f"\n\n{entry}",
        )
        .execution_options(synchronize_session=False)
    )
    joined = cast(CursorResult[object], result).rowcount == 1
    if joined:
        await db.refresh(pending)
    return joined


def _entry(report: CeoReport) -> str:
    text = report.text if len(report.text) <= ENTRY_CHARS else report.text[: ENTRY_CHARS - 1] + "…"
    return f"{text}\n({', '.join(report.refs)})" if report.refs else text


def _chat_link() -> str | None:
    # Imported here: `labhq.api` imports modules that import this one.
    from labhq.api.public_url import current_public_url

    base = current_public_url()
    return f"{base}/ceo" if base else None


async def recent_reports(db: AsyncSession, *, limit: int = 50) -> list[ReportView]:
    """Newest last, as the chat shows them; the Call Center reads the same list."""
    reports = list(await db.scalars(select(CeoReport).order_by(CeoReport.id.desc()).limit(limit)))
    task_ids = {report.task_id for report in reports if report.task_id is not None}
    tasks = {task.id: task for task in await db.scalars(select(Task).where(Task.id.in_(task_ids)))}
    rows = await db.execute(
        select(CeoReport.task_id, func.max(CeoReport.id))
        .where(CeoReport.task_id.in_(task_ids))
        .group_by(CeoReport.task_id)
    )
    latest_for_task = {task_id: report_id for task_id, report_id in rows}
    views = []
    for report in reversed(reports):
        task = tasks.get(report.task_id) if report.task_id is not None else None
        views.append(
            ReportView(
                id=report.id,
                text=report.text,
                refs=list(report.refs),
                task_id=report.task_id,
                task_title=task.title if task is not None else None,
                awaiting_decision=(
                    task is not None
                    and task.parent_id is None
                    and task.status is TaskStatus.IN_REVIEW
                    and latest_for_task.get(task.id) == report.id
                ),
                created_at=report.created_at,
            )
        )
    return views


async def latest_report(db: AsyncSession) -> ReportView | None:
    reports = await recent_reports(db, limit=1)
    return reports[-1] if reports else None
