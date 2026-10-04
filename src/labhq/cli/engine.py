"""The engine the CLI drives: adapters, runs in worktrees, the scheduler and push requests."""

from dataclasses import dataclass, field

from sqlalchemy import select

from labhq.adapters import AdapterRegistry, default_registry
from labhq.approvals import ApprovalService
from labhq.ceochat_retry import retry_limited_messages
from labhq.cli.context import Context
from labhq.cli.fake_worker import CommittingFakeAdapter
from labhq.cli.pushes import request_pushes
from labhq.cli.statuses import ingest_statuses
from labhq.cli.workspace import WorkspaceRunService
from labhq.db.enums import RunStatus
from labhq.db.models import Approval, Run
from labhq.scheduler import Scheduler, SchedulerSettings, TickReport, get_scheduler_settings
from labhq.usage import UsageSettings, get_usage_settings
from labhq.usage.collect import UsageCollector
from labhq.usage.extractors import ExtractorRegistry, ModelExtractor

FAKE_ADAPTER = "fake"


def usage_extractors(
    context: Context, runs: WorkspaceRunService, settings: UsageSettings
) -> ExtractorRegistry:
    registry = ExtractorRegistry()
    registry.register(
        "model",
        ModelExtractor(
            runs,
            context.sessions,
            settings.usage_extractor_agent_id,
            captured_at=lambda: context.clock.now().isoformat(),
        ),
    )
    return registry


def cli_adapters() -> AdapterRegistry:
    """The built-in adapters, with the fake replaced by one that commits like a worker."""
    registry = default_registry.copy()
    registry.register(FAKE_ADAPTER, CommittingFakeAdapter, replace=True)
    return registry


@dataclass
class PassReport:
    started: list[int] = field(default_factory=list)
    finished: list[int] = field(default_factory=list)
    timed_out: list[int] = field(default_factory=list)
    reaped: list[int] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)

    def absorb(self, tick: TickReport) -> None:
        self.started += tick.started
        self.finished += tick.finished
        self.timed_out += tick.timed_out
        self.reaped += tick.reaped

    @property
    def failed(self) -> list[Run]:
        return [run for run in self.runs if run.status is not RunStatus.SUCCEEDED]


class Engine:
    def __init__(
        self,
        context: Context,
        registry: AdapterRegistry | None = None,
        settings: SchedulerSettings | None = None,
        extractors: ExtractorRegistry | None = None,
    ) -> None:
        self._context = context
        usage_settings = get_usage_settings()
        self._usage_settings = usage_settings
        scheduler_settings = settings or get_scheduler_settings()
        self._tick_seconds = scheduler_settings.tick_seconds
        self.runs = WorkspaceRunService(
            context.sessions,
            clock=context.clock,
            registry=registry or cli_adapters(),
            settings=context.settings,
        )
        self.scheduler = Scheduler(
            context.sessions,
            clock=context.clock,
            runs=self.runs,
            settings=scheduler_settings,
            usage_settings=usage_settings,
        )
        self.usage = UsageCollector(
            context.sessions,
            clock=context.clock,
            extractors=extractors or usage_extractors(context, self.runs, usage_settings),
            settings=usage_settings,
        )
        self.approvals = ApprovalService(context.sessions, clock=context.clock)

    async def run_pass(self) -> PassReport:
        """One scheduler tick, then wait for the runs it started and record how they ended."""
        report = PassReport()
        report.absorb(await self.scheduler.tick())
        report.absorb(await self.scheduler.settle())
        await self._after(report, report.finished)
        return report

    async def tick_pass(self) -> PassReport:
        """One scheduler tick that leaves started runs running; the caller ticks on a timer."""
        report = PassReport()
        tick = await self.scheduler.tick()
        report.absorb(tick)
        await self._after(report, tick.finished)
        return report

    async def run_loop(self, max_ticks: int | None = None) -> PassReport:
        """Tick on the clock until stopped (or for `max_ticks`); shut runs down on the way out."""
        report = PassReport()
        ticks = 0
        try:
            while max_ticks is None or ticks < max_ticks:
                tick = await self.scheduler.tick()
                report.absorb(tick)
                await self._after(report, tick.finished)
                ticks += 1
                await self._context.clock.sleep(self._tick_seconds)
        finally:
            # Interrupted runs end as `interrupted`; they have nothing to publish.
            await self.scheduler.shutdown()
        return report

    async def _after(self, report: PassReport, finished: list[int]) -> None:
        if not finished:
            return
        async with self._context.sessions() as db:
            runs = await db.scalars(select(Run).where(Run.id.in_(finished)).order_by(Run.id))
            report.runs += list(runs)
        # Before anything else reads the finished runs: a limit notice holds new runs.
        await self.usage.collect(finished)
        await retry_limited_messages(
            self._context.sessions, self._context.clock, finished, self._usage_settings
        )
        await ingest_statuses(
            self._context.sessions, self._context.clock, self._context.settings, finished
        )
        report.approvals += await request_pushes(
            self._context.sessions, self.approvals, self._context.settings, finished
        )
