"""Ollama runs through the run engine: usage and cost, resume, interrupt and failures."""

import asyncio
from pathlib import Path

import pytest

from labhq.db.enums import RunStatus
from tests.adapters.fake_ollama import FakeOllama
from tests.runs.conftest import World, sessions, world
from tests.runs.helpers import costs_of, stored_run, task_sessions, use_adapter

# The run engine's fixtures, shared rather than copied.
__all__ = ["sessions", "world"]


async def _use(world: World, server: FakeOllama, tmp_path: Path, **overrides: str) -> None:
    world.registry.register(
        "ollama", server.factory(tmp_path / "ollama", **overrides), replace=True
    )
    await use_adapter(world, "ollama")


async def _execute(world: World, prompt: str = "hi") -> int:
    run = await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt=prompt)
    return run.id


async def test_a_finished_run_records_usage_and_a_zero_cost(world: World, tmp_path: Path) -> None:
    await _use(world, FakeOllama(reply=lambda messages: "all done"), tmp_path)
    run_id = await _execute(world)

    run = await stored_run(world, run_id)
    assert (run.adapter, run.status) == ("ollama", RunStatus.SUCCEEDED)
    assert run.usage == {"input_tokens": 11, "output_tokens": 2}
    (cost,) = await costs_of(world, run_id)
    assert (cost.cost_micros, cost.input_tokens, cost.output_tokens) == (0, 11, 2)
    assert cost.model == "tiny:1b"


async def test_the_session_flows_through_agent_task_sessions(world: World, tmp_path: Path) -> None:
    server = FakeOllama()
    await _use(world, server, tmp_path)
    first = await stored_run(world, await _execute(world, "Remember AURORA-7."))
    second = await stored_run(world, await _execute(world, "What was the codeword?"))

    (row,) = await task_sessions(world)
    assert (row.adapter, row.session_id) == ("ollama", first.session_id_after)
    assert second.session_id_before == second.session_id_after == first.session_id_after
    assert [m["content"] for m in server.requests[1]["messages"]] == [
        "Remember AURORA-7.",
        "OK",
        "What was the codeword?",
    ]


async def test_interrupt_ends_the_run_as_interrupted(world: World, tmp_path: Path) -> None:
    server = FakeOllama(hold=True)
    await _use(world, server, tmp_path)
    active = await world.service.start(agent_id=world.agent_id, task_id=world.task_id, prompt="x")
    waiter = asyncio.create_task(active.wait())
    await server.held.wait()
    await active.interrupt()
    run = await stored_run(world, (await waiter).id)

    assert server.closed_streams == 1
    assert run.status is RunStatus.INTERRUPTED
    assert run.exit is not None
    assert run.exit["terminal_reason"] == "aborted_streaming"


@pytest.mark.parametrize(
    ("server", "overrides", "advice"),
    [
        (FakeOllama(refuse_connections=True), {}, "start it with `ollama serve`"),
        (FakeOllama(), {"model": "missing:3b"}, "pull it with `ollama pull missing:3b`"),
    ],
    ids=["unreachable", "unknown-model"],
)
async def test_a_run_that_cannot_reach_a_model_fails_with_advice(
    world: World, tmp_path: Path, server: FakeOllama, overrides: dict[str, str], advice: str
) -> None:
    await _use(world, server, tmp_path, **overrides)
    run = await stored_run(world, await _execute(world))

    assert run.status is RunStatus.FAILED
    assert run.exit is not None
    assert advice in run.exit["errors"][0]
    assert run.session_id_after is None
    assert await task_sessions(world) == []
