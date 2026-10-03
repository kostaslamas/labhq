"""What the loops work on, and the loops labhq ships with."""

from dataclasses import dataclass

from sqlalchemy import select

from labhq.cli.context import Context
from labhq.cli.engine import Engine
from labhq.cli.statuses import ingest_statuses
from labhq.db.models import Run
from labhq.economy.graphify import refresh_loop
from labhq.health.monitor import health_step
from labhq.it import it_step
from labhq.live import live_feed
from labhq.meetings.channels.loop import chat_step
from labhq.notify import Dispatcher
from labhq.program.loops import LoopRegistry, Step
from labhq.scheduler.reaper import LIVE_STATUSES


@dataclass(frozen=True)
class Services:
    context: Context
    engine: Engine
    dispatcher: Dispatcher

    async def close(self) -> None:
        """Interrupt live runs so they end as `interrupted`, not as orphans for the reaper."""
        await self.engine.scheduler.shutdown()


def _scheduler(services: Services) -> Step:
    return services.engine.tick_pass


def _notifications(services: Services) -> Step:
    return services.dispatcher.dispatch_pending


def _statuses(services: Services) -> Step:
    async def ingest_live() -> int:
        # A run's status file is read when it ends; live runs are read on this timer.
        context = services.context
        async with context.sessions() as db:
            live = list(
                await db.scalars(
                    select(Run.id).where(Run.status.in_(LIVE_STATUSES), Run.task_id.is_not(None))
                )
            )
        return len(await ingest_statuses(context.sessions, context.clock, context.settings, live))

    return ingest_live


default_loops: LoopRegistry[Services] = LoopRegistry()
default_loops.register("scheduler", "scheduler_interval_seconds", _scheduler)
default_loops.register("notifications", "notify_interval_seconds", _notifications)
default_loops.register("statuses", "status_interval_seconds", _statuses)
default_loops.register("live", "live_interval_seconds", live_feed)
default_loops.register("health", "health_interval_seconds", health_step)
default_loops.register("graphify", "graphify_interval_seconds", refresh_loop)
default_loops.register("it", "health_interval_seconds", it_step)
default_loops.register("chat", "chat_interval_seconds", chat_step)
