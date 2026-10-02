"""The scheduler: enqueue wakeups, dispatch them into runs, stop overdue and stale runs.

One asyncio lock serialises the scheduler's own decisions inside the process; the
database statements in `checkout` keep them correct across processes as well. Every
instant comes from the injected clock, so tests move time instead of waiting for it.
"""

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.budgets import BudgetSettings, Decision, check
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, RunStatus, WakeupStatus
from labhq.db.models import Agent, Run, WakeupRequest
from labhq.runs import RunStartError
from labhq.scheduler.checkout import checkout, release, reserve_run
from labhq.scheduler.launch import (
    LaunchedRun,
    Launcher,
    LaunchRequest,
    Preparer,
    default_preparer,
)
from labhq.scheduler.processes import ProcessTerminator, terminator_for
from labhq.scheduler.reaper import (
    RunToStop,
    close_run,
    overdue_runs,
    relabel_interrupted,
    stale_runs,
)
from labhq.scheduler.settings import SchedulerSettings, get_scheduler_settings, limits_for
from labhq.scheduler.sources import Trigger, WakeupSources, WakeupSpec, default_sources
from labhq.scheduler.wakeups import Enqueued, enqueue, wake


@dataclass
class RunHandle:
    run_id: int
    task_id: int | None
    launched: LaunchedRun
    driver: "asyncio.Task[None] | None" = None
    # Set when the scheduler interrupted the run, e.g. for a timeout.
    stopping: RunToStop | None = None
    stop_status: RunStatus | None = None
    stop_requested_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SweepReport:
    timed_out: list[int] = field(default_factory=list)
    reaped: list[int] = field(default_factory=list)


class Scheduler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        launcher: Launcher,
        preparer: Preparer = default_preparer,
        sources: WakeupSources = default_sources,
        settings: SchedulerSettings | None = None,
        budget_settings: BudgetSettings | None = None,
        terminator: ProcessTerminator | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._launcher = launcher
        self._preparer = preparer
        self._sources = sources
        self._settings = settings or get_scheduler_settings()
        self._budget_settings = budget_settings
        self._terminator: Callable[[], ProcessTerminator] = (
            (lambda: terminator) if terminator is not None else terminator_for
        )
        self._lock = asyncio.Lock()
        self._handles: dict[int, RunHandle] = {}

    @property
    def handles(self) -> dict[int, RunHandle]:
        return dict(self._handles)

    async def wake(self, trigger: Trigger) -> list[Enqueued]:
        async with self._lock, self._sessions() as db:
            result = await wake(
                db,
                trigger,
                self._clock,
                sources=self._sources,
                budget_settings=self._budget_settings,
            )
            await db.commit()
            return result

    async def enqueue(self, spec: WakeupSpec) -> Enqueued:
        async with self._lock, self._sessions() as db:
            result = await enqueue(db, spec, self._clock, budget_settings=self._budget_settings)
            await db.commit()
            return result

    async def tick(self) -> list[int]:
        """One scheduling pass: stop what must stop, then start what may start."""
        await self.sweep()
        return await self.dispatch()

    async def dispatch(self) -> list[int]:
        """Start a run for every pending request that may start now; return their ids."""
        async with self._lock:
            async with self._sessions() as db:
                pending = list(
                    await db.scalars(
                        select(WakeupRequest.id)
                        .where(WakeupRequest.status == WakeupStatus.PENDING)
                        .order_by(WakeupRequest.id)
                    )
                )
            started = []
            for request_id in pending:
                run_id = await self._dispatch_one(request_id)
                if run_id is not None:
                    started.append(run_id)
            return started

    async def sweep(self) -> SweepReport:
        """Stop runs past their timeout, then close runs whose heartbeat went stale."""
        async with self._lock:
            now = self._clock.now()
            async with self._sessions() as db:
                overdue = await overdue_runs(db, now, self._settings)
            timed_out = [t.run_id for t in overdue if await self._time_out(t, now)]
            async with self._sessions() as db:
                stale = await stale_runs(db, now, self._settings)
            reaped = [t.run_id for t in stale if await self._stop(t, RunStatus.FAILED, now)]
            return SweepReport(timed_out=timed_out, reaped=reaped)

    async def drain(self) -> None:
        """Wait until every run this scheduler started has ended."""
        drivers = [h.driver for h in self._handles.values() if h.driver is not None]
        await asyncio.gather(*drivers, return_exceptions=True)

    async def _dispatch_one(self, request_id: int) -> int | None:
        async with self._sessions() as db:
            request = await db.get_one(WakeupRequest, request_id)
            agent = await db.get_one(Agent, request.agent_id)
            if request.status is not WakeupStatus.PENDING:
                return None
            # New agents need approval before they act (plan §5, rule 4).
            if agent.status is not AgentStatus.ACTIVE:
                return None
            now = self._clock.now()
            budget = await check(db, agent.id, self._clock, self._budget_settings)
            if budget.decision is Decision.STOP:
                request.status, request.updated_at = WakeupStatus.REFUSED, now
                await db.commit()
                return None
            run_id = await self._reserve(db, request, agent, now)
            if run_id is None:
                # Still waiting; keep a warning the budget check may have recorded.
                await db.commit()
                return None
            request.status, request.run_id, request.updated_at = (
                WakeupStatus.DISPATCHED,
                run_id,
                now,
            )
            await db.commit()
        await self._launch(request, run_id)
        return run_id

    async def _reserve(
        self, db: AsyncSession, request: WakeupRequest, agent: Agent, now: datetime
    ) -> int | None:
        limits = limits_for(agent.config, self._settings)
        run_id = await reserve_run(
            db,
            agent_id=agent.id,
            task_id=request.task_id,
            adapter=agent.adapter,
            concurrency=limits.concurrency,
            now=now,
        )
        if run_id is None or request.task_id is None:
            return run_id
        if await checkout(db, request.task_id, run_id, now):
            return run_id
        # Another run holds the task; the reservation never started, so it leaves no trace.
        await db.execute(delete(Run).where(Run.id == run_id))
        return None

    async def _launch(self, request: WakeupRequest, run_id: int) -> None:
        target = RunToStop(run_id, request.task_id, {})
        try:
            spec = await self._preparer(request)
            launched = await self._launcher(
                LaunchRequest(request.agent_id, request.task_id, run_id, spec)
            )
        except RunStartError:
            # The run is already recorded as failed; only the checkout is left to free.
            await self._close(target, RunStatus.FAILED)
            return
        except Exception as error:
            failed = RunToStop(
                run_id, request.task_id, {"error": type(error).__name__, "message": str(error)}
            )
            await self._close(failed, RunStatus.FAILED)
            return
        handle = RunHandle(run_id, request.task_id, launched)
        self._handles[run_id] = handle
        handle.driver = asyncio.create_task(self._drive(handle))

    async def _drive(self, handle: RunHandle) -> None:
        # A forced stop cancels this task and settles the run itself.
        await handle.launched.wait()
        self._handles.pop(handle.run_id, None)
        now = self._clock.now()
        async with self._sessions() as db:
            if handle.stopping is not None and handle.stop_status is not None:
                await relabel_interrupted(db, handle.stopping, handle.stop_status, now)
            elif handle.task_id is not None:
                await release(db, handle.task_id, handle.run_id, now)
            await db.commit()

    async def _time_out(self, target: RunToStop, now: datetime) -> bool:
        handle = self._handles.get(target.run_id)
        if handle is None:
            return await self._stop(target, RunStatus.TIMED_OUT, now)
        if handle.stop_requested_at is None:
            handle.stopping, handle.stop_status = target, RunStatus.TIMED_OUT
            handle.stop_requested_at = now
            with contextlib.suppress(Exception):
                await handle.launched.interrupt()
            return True
        if now < handle.stop_requested_at + self._settings.stop_grace:
            return False
        # The interrupt went unanswered for the whole grace period.
        return await self._stop(target, RunStatus.TIMED_OUT, now)

    async def _stop(self, target: RunToStop, status: RunStatus, now: datetime) -> bool:
        """End a run by force: its process tree, its driver, then its record."""
        handle = self._handles.pop(target.run_id, None)
        if handle is not None:
            if handle.launched.pid is not None:
                self._terminator().kill(handle.launched.pid)
            if handle.driver is not None:
                handle.driver.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await handle.driver
        return await self._close(target, status, now)

    async def _close(
        self, target: RunToStop, status: RunStatus, now: datetime | None = None
    ) -> bool:
        async with self._sessions() as db:
            closed = await close_run(db, target, status, now or self._clock.now())
            await db.commit()
            return closed
