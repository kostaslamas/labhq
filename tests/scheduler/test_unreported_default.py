"""An agent that never reports stops by default, and its manager is told."""

import pytest
from sqlalchemy import select

from labhq.db.enums import TaskStatus, WakeupStatus
from labhq.db.models import WakeupRequest
from labhq.scheduler import SchedulerSettings
from tests.scheduler.conftest import World, build_scheduler
from tests.scheduler.helpers import get_task, give_manager, on_task

DEFAULT_LIMIT = SchedulerSettings().max_unreported_runs


@pytest.fixture
def auto_next_turn() -> bool:
    return True


def test_the_default_limit_is_not_zero() -> None:
    assert DEFAULT_LIMIT > 0


async def test_an_agent_over_the_default_limit_is_stopped_and_its_manager_told(
    world: World,
) -> None:
    manager_id = await give_manager(world)
    # The shared settings pin a small limit for other tests; this one runs on the default.
    settings = world.settings.model_copy(
        update={"max_unreported_runs": DEFAULT_LIMIT, "stall_alert_runs": 0}
    )
    scheduler = build_scheduler(world.sessions, world.clock, world.registry, settings)
    world.schedulers.append(scheduler)

    await scheduler.enqueue(on_task(world, "initial"))
    for turn in range(1, DEFAULT_LIMIT + 1):
        assert len((await scheduler.tick()).started) == 1
        await scheduler.settle()
        expected = TaskStatus.BLOCKED if turn == DEFAULT_LIMIT else TaskStatus.IN_PROGRESS
        assert (await get_task(world, world.task_id)).status is expected

    async with world.sessions() as db:
        told = list(
            await db.scalars(
                select(WakeupRequest).where(
                    WakeupRequest.agent_id == manager_id,
                    WakeupRequest.task_id == world.task_id,
                    WakeupRequest.status == WakeupStatus.PENDING,
                )
            )
        )
    assert len(told) == 1
