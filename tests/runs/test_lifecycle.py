"""A run on the fake adapter, recorded from start to terminal status."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from labhq.adapters import AdapterEvent, FakeAdapter, FakeScript, RunRequest
from labhq.db.enums import RunStatus
from labhq.money import usd_to_micros
from labhq.runs import RunStartError
from tests.runs.conftest import World
from tests.runs.helpers import costs_of, events_of, stored_run, use_adapter


async def test_fake_run_records_run_events_and_one_cost_row(world: World) -> None:
    run = await world.service.execute(
        agent_id=world.agent_id, task_id=world.task_id, prompt="do the task"
    )

    stored = await stored_run(world, run.id)
    assert stored.status is RunStatus.SUCCEEDED
    assert stored.adapter == "fake"
    assert stored.session_id_after == "fake-session-1"
    assert stored.usage == {"input_tokens": 120, "output_tokens": 30}
    assert stored.exit is not None
    assert stored.exit["subtype"] == "success"

    events = await events_of(world, run.id)
    assert [(event.seq, event.kind) for event in events] == [
        (1, "system"),
        (2, "assistant"),
        (3, "result"),
        (4, "final_answer"),
    ]

    costs = await costs_of(world, run.id)
    assert len(costs) == 1
    (cost,) = costs
    assert cost.cost_micros == 12_500 == usd_to_micros("0.0125")
    assert (cost.agent_id, cost.project_id) == (world.agent_id, world.project_id)
    assert (cost.input_tokens, cost.output_tokens, cost.model) == (120, 30, "fake-model")


async def test_heartbeat_moves_with_every_event(world: World) -> None:
    run = await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="x")
    stored = await stored_run(world, run.id)
    events = await events_of(world, run.id)
    assert stored.started_at is not None and stored.heartbeat_at is not None
    stamps = [event.created_at for event in events]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)
    assert stored.started_at < stamps[0]
    assert stored.heartbeat_at >= stamps[-1]
    assert stored.finished_at == stored.heartbeat_at


class _SignalsWhenRecorded(FakeAdapter):
    """Sets `recorded` once the run has consumed, and so committed, every scripted event."""

    def __init__(self, script: FakeScript, recorded: asyncio.Event) -> None:
        super().__init__(script)
        self.recorded = recorded

    async def events(self) -> AsyncIterator[AdapterEvent]:
        seen = 0
        async for event in super().events():
            yield event
            seen += 1
            if seen == len(self.script.events):
                self.recorded.set()


async def test_heartbeat_is_committed_while_the_run_is_live(world: World) -> None:
    world.fake.wait_for_interrupt = True
    recorded = asyncio.Event()
    world.registry.register(
        "fake", lambda: _SignalsWhenRecorded(world.fake, recorded), replace=True
    )
    active = await world.service.start(agent_id=world.agent_id, task_id=world.task_id, prompt="x")
    waiter = asyncio.create_task(active.wait())
    await recorded.wait()

    live = await stored_run(world, active.run_id)
    assert live.status is RunStatus.RUNNING
    assert live.heartbeat_at is not None and live.started_at is not None
    assert live.heartbeat_at > live.started_at
    assert len(await events_of(world, active.run_id)) == len(world.fake.events)

    await active.interrupt()
    assert (await waiter).status is RunStatus.INTERRUPTED


async def test_an_adapter_failure_ends_the_run_as_failed_without_cost(world: World) -> None:
    world.fake.fail_with = RuntimeError("model went away")
    run = await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="x")
    stored = await stored_run(world, run.id)
    assert stored.status is RunStatus.FAILED
    assert stored.exit == {"error": "RuntimeError", "message": "model went away"}
    assert await costs_of(world, run.id) == []
    assert world.fake.closes == 1


async def test_a_failed_terminal_result_still_records_its_cost(world: World) -> None:
    world.fake.subtype, world.fake.is_error = "error_max_turns", True
    world.fake.terminal_reason = "max_turns"
    run = await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="x")
    assert (await stored_run(world, run.id)).status is RunStatus.FAILED
    assert [cost.cost_micros for cost in await costs_of(world, run.id)] == [12_500]


async def test_a_missing_cost_is_recorded_as_zero(world: World) -> None:
    world.fake.cost_usd = None
    run = await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="x")
    assert [cost.cost_micros for cost in await costs_of(world, run.id)] == [0]


class _CannotStart(FakeAdapter):
    async def start(self, request: RunRequest) -> None:
        raise LookupError("no claude binary on PATH")


async def test_a_start_failure_is_recorded_and_raised(world: World) -> None:
    world.registry.register("broken", _CannotStart)
    await use_adapter(world, "broken")
    with pytest.raises(RunStartError) as raised:
        await world.service.start(agent_id=world.agent_id, task_id=world.task_id, prompt="x")
    stored = await stored_run(world, raised.value.run_id)
    assert stored.status is RunStatus.FAILED
    assert stored.exit == {"error": "LookupError", "message": "no claude binary on PATH"}


async def test_input_sent_to_a_live_run_reaches_the_adapter(world: World) -> None:
    world.fake.events = [AdapterEvent("assistant", {"text": "working"})]
    active = await world.service.start(agent_id=world.agent_id, task_id=world.task_id, prompt="x")
    await active.send("use the staging database")
    await active.wait()
    assert world.fake.inputs == ["use the staging database"]
