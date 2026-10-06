"""A scheduler on agents of tmux kinds (run by the fake adapter) and plan readings."""

from datetime import datetime
from typing import Any

from sqlalchemy import select

from labhq.adapters import FakeAdapter
from labhq.db.models import Notification, UsageReading
from labhq.runs import RunService
from labhq.scheduler import Scheduler
from labhq.usage import UsageSettings
from tests.scheduler.conftest import BUDGETS, SETTINGS, World
from tests.scheduler.helpers import set_agent

PLAN = UsageSettings(plan_usage_warn_percent=50, plan_usage_stop_percent=70)


async def on_kind(world: World, config: dict[str, Any]) -> Scheduler:
    """Put the world's agent on the tmux adapter; the fake answers for every kind."""
    world.registry.register("tmux", lambda: FakeAdapter(world.fake), replace=True)
    await set_agent(world, adapter="tmux", config=config)
    return plan_scheduler(world)


def plan_scheduler(world: World, settings: UsageSettings = PLAN) -> Scheduler:
    scheduler = Scheduler(
        world.sessions,
        clock=world.clock,
        runs=RunService(world.sessions, clock=world.clock, registry=world.registry),
        settings=SETTINGS,
        budget_settings=BUDGETS,
        usage_settings=settings,
    )
    # The world's teardown stops every scheduler it knows, so no run outlives its test (#150).
    world.schedulers.append(scheduler)
    return scheduler


async def add_reading(
    world: World,
    kind: str,
    value: float | None,
    *,
    window: str = "five_hour",
    resets_at: datetime | None = None,
    error: str | None = None,
) -> None:
    async with world.sessions() as db:
        db.add(
            UsageReading(
                agent_id=world.agent_id,
                agent_kind=kind,
                source="statusline",
                unit="percent" if value is not None else None,
                window=window if value is not None else None,
                value=value,
                resets_at=resets_at,
                error=error,
                created_at=world.clock.now(),
            )
        )
        await db.commit()


async def notifications(world: World) -> list[Notification]:
    async with world.sessions() as db:
        return list(await db.scalars(select(Notification).where(Notification.kind == "plan_usage")))
