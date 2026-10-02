"""The scheduler loop: police live runs, reap stale ones, start what may start.

One `tick()` is one pass and never sleeps; `run_forever()` paces ticks on the injected
clock, so tests drive the scheduler tick by tick on a `FakeClock`.

Liveness has two guards with separate jobs. The timeout bounds a run this process owns:
past it the run is interrupted, and past the grace after that it is abandoned. The
reaper catches runs nobody owns any more (a crashed scheduler, a killed worker): this
process beats the heartbeat of every run it holds on each tick, so a heartbeat only goes
stale when its owner is gone.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.budgets import BudgetSettings
from labhq.clock import Clock
from labhq.db.enums import RunStatus
from labhq.db.models import Run
from labhq.runs import ActiveRun, RunService, RunStartError
from labhq.scheduler.checkout import release
from labhq.scheduler.dispatch import Dispatch, Verdict, dispatch_one, pending_wakeup_ids
from labhq.scheduler.reaper import LIVE_STATUSES, reap_stale_runs
from labhq.scheduler.settings import SchedulerSettings, get_scheduler_settings
from labhq.scheduler.sources import SourceRegistry, default_sources
from labhq.scheduler.wakeups import EnqueueResult, Wakeup, enqueue

log = logging.getLogger(__name__)

TIMEOUT_REASON = "timeout"


@dataclass
class LiveRun:
    run_id: int
    active: ActiveRun
    waiter: "asyncio.Task[Run]"
    deadline: datetime
    timeout_seconds: int
    timed_out_at: datetime | None = None


@dataclass
class TickReport:
    started: list[int] = field(default_factory=list)
    finished: list[int] = field(default_factory=list)
    timed_out: list[int] = field(default_factory=list)
    reaped: list[int] = field(default_factory=list)
    waiting: dict[int, Verdict] = field(default_factory=dict)


class Scheduler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        runs: RunService,
        sources: SourceRegistry = default_sources,
        settings: SchedulerSettings | None = None,
        budget_settings: BudgetSettings | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._runs = runs
        self._sources = sources
        self._settings = settings or get_scheduler_settings()
        self._budget_settings = budget_settings
        self._live: dict[int, LiveRun] = {}
        # Abandoned waiters, kept referenced until their cancellation has run.
        self._abandoned: set[asyncio.Task[Run]] = set()

    @property
    def live_run_ids(self) -> list[int]:
        return sorted(self._live)

    async def enqueue(self, wakeup: Wakeup) -> EnqueueResult:
        async with self._sessions() as db:
            result = await enqueue(
                db,
                wakeup,
                self._clock,
                sources=self._sources,
                budget_settings=self._budget_settings,
            )
            await db.commit()
            return result

    async def tick(self) -> TickReport:
        report = TickReport()
        await self._police(report)
        await self._collect(report)
        async with self._sessions() as db:
            limit = timedelta(seconds=self._settings.heartbeat_limit_seconds)
            report.reaped = await reap_stale_runs(db, self._clock, limit)
            await db.commit()
        await self._dispatch(report)
        return report

    async def run_forever(self) -> None:
        try:
            while True:
                await self.tick()
                await self._clock.sleep(self._settings.tick_seconds)
        finally:
            await self.shutdown()

    async def settle(self) -> TickReport:
        """Wait for every live run to end, then record their ends. Used by tests and shutdown."""
        waiters = {live.waiter for live in self._live.values()}
        if waiters:
            await asyncio.wait(waiters)
        report = TickReport()
        await self._collect(report)
        return report

    async def shutdown(self) -> None:
        """Interrupt every live run and record how each ended."""
        for live in list(self._live.values()):
            await _interrupt(live)
        await self.settle()

    async def _police(self, report: TickReport) -> None:
        now = self._clock.now()
        grace = timedelta(seconds=self._settings.interrupt_grace_seconds)
        for live in list(self._live.values()):
            if live.waiter.done():
                continue
            if live.timed_out_at is None and now >= live.deadline:
                live.timed_out_at = now
                report.timed_out.append(live.run_id)
                await _interrupt(live)
            elif live.timed_out_at is not None and now >= live.timed_out_at + grace:
                # The run ignored its interrupt: stop waiting for it and record it as is.
                live.waiter.cancel()
                self._abandoned.add(live.waiter)
                live.waiter.add_done_callback(self._abandoned.discard)
                await self._close(live, report)
        await self._beat(now)

    async def _beat(self, now: datetime) -> None:
        running = [run_id for run_id, live in self._live.items() if not live.waiter.done()]
        if not running:
            return
        async with self._sessions() as db:
            await db.execute(
                update(Run)
                .where(Run.id.in_(running), Run.status == RunStatus.RUNNING)
                .values(heartbeat_at=now)
                .execution_options(synchronize_session=False)
            )
            await db.commit()

    async def _collect(self, report: TickReport) -> None:
        for live in list(self._live.values()):
            if live.waiter.done():
                await self._close(live, report)

    async def _close(self, live: LiveRun, report: TickReport) -> None:
        self._live.pop(live.run_id, None)
        async with self._sessions() as db:
            if live.timed_out_at is not None:
                await self._mark_timed_out(db, live)
            await release(db, live.run_id)
            await db.commit()
        report.finished.append(live.run_id)

    async def _mark_timed_out(self, db: AsyncSession, live: LiveRun) -> None:
        run = await db.get_one(Run, live.run_id, populate_existing=True)
        now = self._clock.now()
        run.status = RunStatus.TIMED_OUT
        run.finished_at = run.finished_at or now
        run.exit = {
            **(run.exit or {}),
            "stopped_by": TIMEOUT_REASON,
            "timeout_seconds": live.timeout_seconds,
            "timed_out_at": live.timed_out_at.isoformat() if live.timed_out_at else None,
        }

    async def _dispatch(self, report: TickReport) -> None:
        async with self._sessions() as db:
            wakeup_ids = await pending_wakeup_ids(db)
        for wakeup_id in wakeup_ids:
            async with self._sessions() as db:
                outcome = await dispatch_one(
                    db,
                    wakeup_id,
                    self._clock,
                    sources=self._sources,
                    settings=self._settings,
                    budget_settings=self._budget_settings,
                )
            if outcome.verdict is Verdict.QUEUED:
                await self._start(outcome, report)
            else:
                report.waiting[wakeup_id] = outcome.verdict

    async def _start(self, dispatch: Dispatch, report: TickReport) -> None:
        assert dispatch.run_id is not None and dispatch.agent_id is not None
        run_id = dispatch.run_id
        try:
            active = await self._runs.start(
                agent_id=dispatch.agent_id,
                task_id=dispatch.task_id,
                prompt=dispatch.prompt,
                run_id=run_id,
            )
        except RunStartError:
            # Already recorded as failed by the run service; only the task is ours to free.
            await self._release_failed(run_id, None)
            report.finished.append(run_id)
            return
        except Exception as error:
            log.exception("run %s could not start", run_id)
            await self._release_failed(run_id, error)
            report.finished.append(run_id)
            return
        now = self._clock.now()
        self._live[run_id] = LiveRun(
            run_id=run_id,
            active=active,
            waiter=asyncio.create_task(active.wait()),
            deadline=now + timedelta(seconds=dispatch.timeout_seconds),
            timeout_seconds=dispatch.timeout_seconds,
        )
        report.started.append(run_id)

    async def _release_failed(self, run_id: int, error: Exception | None) -> None:
        async with self._sessions() as db:
            if error is not None:
                await db.execute(
                    update(Run)
                    .where(Run.id == run_id, Run.status.in_(LIVE_STATUSES))
                    .values(
                        status=RunStatus.FAILED,
                        finished_at=self._clock.now(),
                        exit={"error": type(error).__name__, "message": str(error)},
                    )
                    .execution_options(synchronize_session=False)
                )
            await release(db, run_id)
            await db.commit()


async def _interrupt(live: LiveRun) -> None:
    try:
        await live.active.interrupt()
    except Exception:
        # A failed interrupt leaves the grace period to settle the run.
        log.exception("interrupt of run %s failed", live.run_id)
