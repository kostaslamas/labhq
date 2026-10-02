"""`start(run_id=...)` adopts a queued run instead of inserting a new one."""

import pytest
from sqlalchemy import func, select

from labhq.db.enums import RunStatus
from labhq.db.models import Run
from labhq.runs import RunNotQueuedError
from tests.runs.conftest import World
from tests.runs.helpers import stored_run


async def _queued(world: World, *, task_id: int | None) -> int:
    async with world.sessions() as db:
        run = Run(
            agent_id=world.agent_id,
            task_id=task_id,
            adapter="fake",
            status=RunStatus.QUEUED,
            created_at=world.clock.now(),
        )
        db.add(run)
        await db.commit()
        return run.id


async def _run_count(world: World) -> int:
    async with world.sessions() as db:
        return await db.scalar(select(func.count()).select_from(Run)) or 0


async def test_a_queued_run_is_adopted_and_driven_to_its_terminal_status(world: World) -> None:
    run_id = await _queued(world, task_id=world.task_id)

    run = await world.service.execute(
        agent_id=world.agent_id, task_id=world.task_id, prompt="go", run_id=run_id
    )

    assert run.id == run_id
    assert await _run_count(world) == 1
    stored = await stored_run(world, run_id)
    assert stored.status is RunStatus.SUCCEEDED
    assert stored.started_at is not None
    assert stored.created_at < stored.started_at


@pytest.mark.parametrize("task_matches", [True, False])
async def test_a_run_that_is_not_queued_for_this_agent_and_task_is_refused(
    world: World, task_matches: bool
) -> None:
    run_id = await _queued(world, task_id=world.task_id if task_matches else None)
    if task_matches:
        await world.service.execute(
            agent_id=world.agent_id, task_id=world.task_id, prompt="go", run_id=run_id
        )

    with pytest.raises(RunNotQueuedError):
        await world.service.start(
            agent_id=world.agent_id, task_id=world.task_id, prompt="again", run_id=run_id
        )
    # The refused start never reached the adapter.
    assert len(world.fake.requests) == (1 if task_matches else 0)
