"""An interrupted run ends as `interrupted`, never `failed` (spikes/agent_sdk/RESULTS.md)."""

import asyncio

import pytest

from labhq.db.enums import RunStatus
from tests.runs.conftest import World
from tests.runs.helpers import costs_of, stored_run, use_adapter


@pytest.mark.parametrize("adapter", ["claude", "fake"])
async def test_interrupt_ends_the_run_as_interrupted(world: World, adapter: str) -> None:
    world.claude.wait_for_interrupt = world.fake.wait_for_interrupt = True
    await use_adapter(world, adapter)
    active = await world.service.start(
        agent_id=world.agent_id, task_id=world.task_id, prompt="Run `sleep 30`."
    )
    waiter = asyncio.create_task(active.wait())
    await active.interrupt()
    run = await waiter

    stored = await stored_run(world, run.id)
    assert stored.status is RunStatus.INTERRUPTED
    assert stored.exit is not None
    assert stored.exit["subtype"] == "error_during_execution"
    assert stored.exit["terminal_reason"] == "aborted_streaming"
    assert stored.exit["is_error"] is True
    # The turn still cost money up to the interrupt.
    assert len(await costs_of(world, run.id)) == 1


async def test_claude_interrupt_cost_comes_from_the_sdk_result(world: World) -> None:
    world.claude.wait_for_interrupt = True
    await use_adapter(world, "claude")
    active = await world.service.start(agent_id=world.agent_id, task_id=world.task_id, prompt="x")
    waiter = asyncio.create_task(active.wait())
    await active.interrupt()
    run = await waiter
    (cost,) = await costs_of(world, run.id)
    assert cost.cost_micros == 9_700
    assert (cost.input_tokens, cost.cache_read_input_tokens) == (410, 3000)
    assert world.claude.interrupts == 1
    assert world.claude.disconnects == 1


async def test_an_error_during_execution_without_an_abort_is_a_failure(world: World) -> None:
    world.claude.result_overrides = {"subtype": "error_during_execution", "is_error": True}
    world.claude.result_overrides["terminal_reason"] = None
    await use_adapter(world, "claude")
    run = await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="x")
    assert (await stored_run(world, run.id)).status is RunStatus.FAILED
