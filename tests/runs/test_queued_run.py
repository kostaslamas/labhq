"""`RunService.start(run_id=...)` adopts a run queued by the scheduler instead of adding one."""

import pytest
from sqlalchemy import func, select

from labhq.db.enums import RunStatus
from labhq.db.models import Run
from tests.runs.conftest import World
from tests.runs.helpers import stored_run


async def _queued(world: World, task_id: int | None) -> int:
    async with world.sessions() as db:
        run = Run(
            agent_id=world.agent_id,
            task_id=task_id,
            adapter="fake",
            created_at=world.clock.now(),
        )
        db.add(run)
        await db.commit()
        return run.id


async def test_a_queued_run_is_adopted_and_runs_to_its_end(world: World) -> None:
    run_id = await _queued(world, world.task_id)
    run = await world.service.execute(
        agent_id=world.agent_id, task_id=world.task_id, prompt="x", run_id=run_id
    )
    assert run.id == run_id
    stored = await stored_run(world, run_id)
    assert stored.status is RunStatus.SUCCEEDED
    assert stored.started_at is not None and stored.started_at > stored.created_at
    async with world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Run)) == 1


async def test_only_a_queued_run_of_the_same_agent_and_task_is_adopted(world: World) -> None:
    run_id = await _queued(world, None)
    with pytest.raises(ValueError, match="not a queued run"):
        await world.service.start(
            agent_id=world.agent_id, task_id=world.task_id, prompt="x", run_id=run_id
        )
    await world.service.execute(agent_id=world.agent_id, task_id=None, prompt="x", run_id=run_id)
    with pytest.raises(ValueError, match="not a queued run"):
        await world.service.start(agent_id=world.agent_id, task_id=None, prompt="x", run_id=run_id)
