"""After a tmux run: turn what the adapter captured into readings, and hold a reached limit.

The adapter leaves three kinds of event behind: `statusline` (Claude Code's JSON, read with
no model call), `usage_screen` (the pane after the agent's usage command) and `screen_final`
(the end of the pane when the turn ended or stalled). The screens go to the extractor once,
which reports usage and whether a limit notice is shown. A failed extraction is recorded as
a failed reading. A limit notice becomes a 100% reading of the `limit_notice` window, which
the plan check holds until its reset time; the owner is notified through the plan check.
"""

from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db.models import Agent, Run, RunEvent, Task
from labhq.usage.extractors import (
    ExtractorRegistry,
    ExtractorUnavailableError,
    UnknownExtractorError,
)
from labhq.usage.plan import LIMIT_WINDOW, check_agent
from labhq.usage.record import ReadingContext, record_failure, record_readings
from labhq.usage.schema import (
    ExtractionError,
    Reading,
    UsageUnit,
    check_extraction,
    parse_extraction,
)
from labhq.usage.settings import UsageSettings, get_usage_settings
from labhq.usage.statusline import statusline_readings

CAPTURE_KINDS = ("agent", "statusline", "usage_screen", "screen_final")
SCREEN_KINDS = ("usage_screen", "screen_final")


@dataclass
class Captures:
    agent_kind: str | None = None
    statusline: dict[str, Any] | None = None
    screens: list[str] = field(default_factory=list)


@dataclass
class CollectReport:
    readings: int = 0
    failures: list[str] = field(default_factory=list)
    limit_notices: list[int] = field(default_factory=list)


class UsageCollector:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        extractors: ExtractorRegistry,
        settings: UsageSettings | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._extractors = extractors
        self._settings = settings or get_usage_settings()

    async def collect(self, run_ids: list[int]) -> CollectReport:
        report = CollectReport()
        for run_id in run_ids:
            await self._collect_one(run_id, report)
        return report

    async def _collect_one(self, run_id: int, report: CollectReport) -> None:
        async with self._sessions() as db:
            captures = await _captures(db, run_id)
            if captures.agent_kind is None:
                return
            run = await db.get_one(Run, run_id)
            agent = await db.get_one(Agent, run.agent_id)
            project_id = agent.project_id
            if run.task_id is not None:
                task = await db.get(Task, run.task_id)
                project_id = task.project_id if task is not None else project_id
        kind = captures.agent_kind
        context = ReadingContext(
            agent_id=agent.id,
            agent_kind=kind,
            run_id=run_id,
            project_id=project_id,
            source="statusline",
            now=self._clock.now(),
        )
        readings = statusline_readings(captures.statusline) if captures.statusline else []
        screen = "\n".join(captures.screens)
        extracted: list[Reading] = []
        notice: Reading | None = None
        error: str | None = None
        if screen.strip():
            try:
                extracted, notice = await self._extract(screen, kind)
            except (ExtractionError, ExtractorUnavailableError, UnknownExtractorError) as failure:
                error = str(failure)
        async with self._sessions() as db:
            record_readings(db, context, readings)
            screen_context = replace(context, source="screen")
            record_readings(db, screen_context, extracted)
            if error is not None:
                record_failure(db, screen_context, error)
                report.failures.append(error)
            if notice is not None:
                limit_context = replace(context, source=LIMIT_WINDOW)
                record_readings(db, limit_context, [notice])
                report.limit_notices.append(run_id)
            await db.flush()
            await check_agent(db, agent, self._clock, self._settings, kind=kind)
            await db.commit()
        report.readings += len(readings) + len(extracted) + (notice is not None)

    async def _extract(self, screen: str, kind: str) -> tuple[list[Reading], Reading | None]:
        extractor = self._extractors.get(self._settings.usage_extractor)
        raw = await extractor.extract(screen, kind)
        now = self._clock.now()
        max_reset = timedelta(days=self._settings.usage_max_reset_days)
        extraction = check_extraction(
            parse_extraction(raw), screen, captured_at=now, max_reset=max_reset
        )
        if not extraction.limit_notice:
            return list(extraction.readings), None
        resets_at = extraction.limit_resets_at or now + timedelta(
            seconds=self._settings.plan_limit_hold_seconds
        )
        notice = Reading(
            unit=UsageUnit.PERCENT, value=100, window=LIMIT_WINDOW, resets_at=resets_at
        )
        return list(extraction.readings), notice


async def _captures(db: AsyncSession, run_id: int) -> Captures:
    rows = await db.scalars(
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.kind.in_(CAPTURE_KINDS))
        .order_by(RunEvent.seq)
    )
    captures = Captures()
    for row in rows:
        _absorb(captures, row)
    return captures


def _agent(captures: Captures, payload: dict[str, Any]) -> None:
    kind = payload.get("kind")
    captures.agent_kind = kind if isinstance(kind, str) else None


def _statusline(captures: Captures, payload: dict[str, Any]) -> None:
    captures.statusline = payload


def _screen(captures: Captures, payload: dict[str, Any]) -> None:
    text = payload.get("text")
    if isinstance(text, str) and text.strip():
        captures.screens.append(text)


_ABSORB = {"agent": _agent, "statusline": _statusline, **dict.fromkeys(SCREEN_KINDS, _screen)}


def _absorb(captures: Captures, row: RunEvent) -> None:
    _ABSORB[row.kind](captures, row.payload)
