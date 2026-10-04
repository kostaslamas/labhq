"""Enqueue: sources, idempotency keys, and the budget check at the door."""

import asyncio

import pytest

from labhq.db.enums import WakeupSource, WakeupStatus
from labhq.scheduler import InvalidWakeupError, Outcome, Wakeup, default_sources, enqueue
from tests.scheduler.conftest import BUDGETS, World
from tests.scheduler.helpers import on_task, wakeups


async def test_two_wakeups_with_the_same_key_produce_one_request(world: World) -> None:
    first = await world.scheduler.enqueue(on_task(world, "assign:1"))
    second = await world.scheduler.enqueue(on_task(world, "assign:1", reason="retry"))

    assert (first.outcome, second.outcome) == (Outcome.CREATED, Outcome.DUPLICATE)
    assert second.request.id == first.request.id
    rows = await wakeups(world)
    assert len(rows) == 1
    assert rows[0].reason == "" and rows[0].coalesced_count == 0


async def test_racing_enqueues_of_one_key_still_produce_one_request(world: World) -> None:
    results = await asyncio.gather(
        *(world.scheduler.enqueue(on_task(world, "comment:9")) for _ in range(3))
    )
    assert {result.request.id for result in results} == {results[0].request.id}
    assert len(await wakeups(world)) == 1


@pytest.mark.parametrize("source", list(WakeupSource))
async def test_every_source_is_registered_and_enqueues(world: World, source: WakeupSource) -> None:
    wakeup = (
        Wakeup(agent_id=world.agent_id, source=source, idempotency_key=f"{source}:1")
        if source is WakeupSource.OWNER_MESSAGE
        else on_task(world, f"{source}:1", source=source)
    )
    result = await world.scheduler.enqueue(wakeup)
    assert result.outcome is Outcome.CREATED
    assert result.request.source is source
    assert sorted(default_sources.sources()) == sorted(WakeupSource)


@pytest.mark.parametrize("source", [WakeupSource.ASSIGNMENT, WakeupSource.COMMENT])
async def test_task_sources_refuse_a_wakeup_without_a_task(
    world: World, source: WakeupSource
) -> None:
    lone = Wakeup(agent_id=world.agent_id, source=source, idempotency_key="x")
    with pytest.raises(InvalidWakeupError):
        await world.scheduler.enqueue(lone)
    assert await wakeups(world) == []


async def test_a_timer_wakeup_needs_no_task(world: World) -> None:
    timer = Wakeup(agent_id=world.agent_id, source=WakeupSource.TIMER, idempotency_key="t:1")
    result = await world.scheduler.enqueue(timer)
    assert result.outcome is Outcome.CREATED
    assert result.request.task_id is None


async def test_owner_messages_never_coalesce(world: World) -> None:
    for index in (1, 2):
        result = await world.scheduler.enqueue(
            Wakeup(
                agent_id=world.agent_id,
                source=WakeupSource.OWNER_MESSAGE,
                idempotency_key=f"owner:{index}",
                reason=f"message {index}",
            )
        )
        assert result.outcome is Outcome.CREATED
    assert [row.reason for row in await wakeups(world)] == ["message 1", "message 2"]


async def test_enqueue_leaves_the_transaction_to_the_caller(world: World) -> None:
    async with world.sessions() as db:
        result = await enqueue(db, on_task(world, "k"), world.clock, budget_settings=BUDGETS)
        assert result.request.status is WakeupStatus.PENDING
        await db.rollback()
    assert await wakeups(world) == []
