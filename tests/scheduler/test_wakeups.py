"""Enqueue: idempotency keys, coalescing into pending work and the budget at enqueue."""

import asyncio

from sqlalchemy import func, select

from labhq.db.enums import WakeupStatus
from labhq.db.models import BudgetWarning
from labhq.scheduler import EnqueueOutcome
from tests.scheduler.conftest import World
from tests.scheduler.helpers import configure_agent, requests, spec, spend


async def test_two_wakeups_with_one_idempotency_key_produce_one_request(world: World) -> None:
    first = await world.scheduler.enqueue(spec(world, "comment:1"))
    again = await world.scheduler.enqueue(spec(world, "comment:1"))

    assert first.outcome is EnqueueOutcome.CREATED
    assert again.outcome is EnqueueOutcome.DUPLICATE
    assert again.request_id == first.request_id
    rows = await requests(world)
    assert len(rows) == 1
    assert rows[0].coalesced_count == 0


async def test_concurrent_enqueues_with_one_key_produce_one_request(world: World) -> None:
    results = await asyncio.gather(
        *(world.scheduler.enqueue(spec(world, "comment:race")) for _ in range(3))
    )

    assert len({result.request_id for result in results}) == 1
    assert len(await requests(world)) == 1


async def test_wakeups_during_a_run_coalesce_into_one_pending_request(world: World) -> None:
    (held,) = world.scripts.hold()
    await world.scheduler.enqueue(spec(world, "assignment:1"))
    (run_id,) = await world.scheduler.dispatch()

    during = [await world.scheduler.enqueue(spec(world, f"comment:{n}")) for n in range(3)]

    target = during[0].request_id
    assert [result.outcome for result in during] == [
        EnqueueOutcome.CREATED,
        EnqueueOutcome.COALESCED,
        EnqueueOutcome.COALESCED,
    ]
    assert {result.request_id for result in during} == {target}
    pending = [row for row in await requests(world) if row.status is WakeupStatus.PENDING]
    assert [(row.id, row.coalesced_count) for row in pending] == [(target, 2)]
    # The merged run waits for the running one, then carries all three wakeups.
    assert await world.scheduler.dispatch() == []
    await world.scheduler.handles[run_id].launched.interrupt()
    await world.scheduler.drain()
    assert held.interrupts == 1
    assert len(await world.scheduler.dispatch()) == 1
    await world.scheduler.drain()
    assert "2 more wakeups merged" in world.scripts.used[-1].requests[0].prompt


async def test_a_retried_coalesced_wakeup_does_not_count_twice(world: World) -> None:
    await world.scheduler.enqueue(spec(world, "comment:1"))
    merged = await world.scheduler.enqueue(spec(world, "comment:2"))
    retry = await world.scheduler.enqueue(spec(world, "comment:2"))

    assert merged.outcome is EnqueueOutcome.COALESCED
    assert retry.outcome is EnqueueOutcome.DUPLICATE
    assert retry.request_id == merged.request_id
    rows = await requests(world)
    assert [(row.status, row.coalesced_count) for row in rows] == [
        (WakeupStatus.PENDING, 1),
        (WakeupStatus.COALESCED, 0),
    ]
    assert rows[1].coalesced_into_id == rows[0].id


async def test_wakeups_for_different_tasks_stay_separate_requests(world: World) -> None:
    first = await world.scheduler.enqueue(spec(world, "a", task=0))
    second = await world.scheduler.enqueue(spec(world, "b", task=1))
    timer = await world.scheduler.enqueue(spec(world, "c", task=None))

    assert len({first.request_id, second.request_id, timer.request_id}) == 3
    assert all(row.coalesced_count == 0 for row in await requests(world))


async def test_at_full_budget_enqueue_is_refused_and_a_retry_stays_refused(
    world: World,
) -> None:
    await configure_agent(world, budget_micros=1_000_000)
    await spend(world, 1_000_000)

    refused = await world.scheduler.enqueue(spec(world, "comment:1"))
    retry = await world.scheduler.enqueue(spec(world, "comment:1"))

    assert refused.outcome is EnqueueOutcome.REFUSED
    assert retry.outcome is EnqueueOutcome.DUPLICATE
    assert [row.status for row in await requests(world)] == [WakeupStatus.REFUSED]
    assert await world.scheduler.dispatch() == []


async def test_at_80_percent_enqueue_proceeds_and_the_warning_is_recorded(world: World) -> None:
    await configure_agent(world, budget_micros=1_000_000)
    await spend(world, 800_000)

    result = await world.scheduler.enqueue(spec(world, "comment:1"))

    assert result.outcome is EnqueueOutcome.CREATED
    async with world.sessions() as db:
        warnings = await db.scalar(select(func.count()).select_from(BudgetWarning))
    assert warnings == 1
