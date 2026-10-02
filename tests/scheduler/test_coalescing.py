"""While an agent runs, new wakeups for the same task merge into one pending request."""

from labhq.db.enums import RunStatus, WakeupStatus
from labhq.scheduler import Outcome
from tests.scheduler.conftest import World
from tests.scheduler.helpers import add_task, get_run, on_task, wakeups


async def _start_a_long_run(world: World) -> int:
    world.fake.wait_for_interrupt = True
    await world.scheduler.enqueue(on_task(world, "assign:first"))
    report = await world.scheduler.tick()
    (run_id,) = report.started
    return run_id


async def test_wakeups_during_a_run_coalesce_with_the_right_count(world: World) -> None:
    run_id = await _start_a_long_run(world)

    results = [
        await world.scheduler.enqueue(on_task(world, f"comment:{n}", reason=f"mention {n}"))
        for n in range(4)
    ]

    assert [result.outcome for result in results] == [Outcome.CREATED] + [Outcome.COALESCED] * 3
    pending = [row for row in await wakeups(world) if row.status is WakeupStatus.PENDING]
    assert len(pending) == 1
    assert pending[0].coalesced_count == 3
    assert all(result.request.id == pending[0].id for result in results)
    assert (await world.scheduler.tick()).started == []
    assert world.scheduler.live_run_ids == [run_id]


async def test_a_retried_merged_wakeup_is_a_duplicate_not_another_merge(world: World) -> None:
    await _start_a_long_run(world)
    await world.scheduler.enqueue(on_task(world, "comment:1"))
    await world.scheduler.enqueue(on_task(world, "comment:2"))
    retry = await world.scheduler.enqueue(on_task(world, "comment:2"))

    assert retry.outcome is Outcome.DUPLICATE
    pending = [row for row in await wakeups(world) if row.status is WakeupStatus.PENDING]
    assert [row.coalesced_count for row in pending] == [1]


async def test_wakeups_for_another_task_do_not_merge(world: World) -> None:
    await _start_a_long_run(world)
    other = await add_task(world, "Other task")
    await world.scheduler.enqueue(on_task(world, "a"))
    second = await world.scheduler.enqueue(on_task(world, "b", task_id=other))
    assert second.outcome is Outcome.CREATED


async def test_the_merged_request_starts_once_the_run_ends_and_tells_the_agent(
    world: World,
) -> None:
    first = await _start_a_long_run(world)
    for n in range(3):
        await world.scheduler.enqueue(on_task(world, f"c:{n}", reason="review asked"))

    await world.scheduler.shutdown()
    assert (await get_run(world, first)).status is RunStatus.INTERRUPTED
    world.fake.wait_for_interrupt = False
    report = await world.scheduler.tick()

    (second,) = report.started
    await world.scheduler.settle()
    assert (await get_run(world, second)).status is RunStatus.SUCCEEDED
    prompt = world.fake.requests[-1].prompt
    assert "Reason: review asked" in prompt
    assert "2 further wakeups arrived meanwhile." in prompt
    assert "Task #" in prompt
