"""The default extractor: one ordinary run of the extractor agent, its cost recorded."""

import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from labhq.adapters import AdapterEvent, FakeAdapter, FakeScript
from labhq.db.models import CostEvent, Run
from labhq.runs import RunService
from labhq.usage.extractors import ExtractorUnavailableError, ModelExtractor
from tests.scheduler.conftest import World
from tests.usage.extracting import ANSWERS

ANSWER = json.dumps(ANSWERS["codex_status.txt"])


class Answering(FakeAdapter):
    """Reports a final text in its result event, as the Claude adapter's result message does."""

    async def events(self) -> AsyncIterator[AdapterEvent]:
        async for event in super().events():
            if event.kind == "result":
                yield AdapterEvent("result", {**event.payload, "result": ANSWER})
                continue
            yield event


def extractor(world: World, agent_id: int | None, script: FakeScript) -> ModelExtractor:
    world.registry.register("fake", lambda: Answering(script), replace=True)
    runs = RunService(world.sessions, clock=world.clock, registry=world.registry)
    return ModelExtractor(runs, world.sessions, agent_id, captured_at=lambda: "2026-10-02T09:00Z")


async def test_the_answer_comes_from_one_recorded_run_with_its_cost(world: World) -> None:
    script = FakeScript()

    answer = await extractor(world, world.agent_id, script).extract("31% used", "codex")

    assert answer == ANSWER
    (request,) = script.requests
    assert "codex" in request.prompt and "31% used" in request.prompt
    async with world.sessions() as db:
        (run,) = list(await db.scalars(select(Run)))
        (cost,) = list(await db.scalars(select(CostEvent)))
    assert run.task_id is None
    assert (cost.run_id, cost.cost_micros) == (run.id, 12_500)


async def test_without_an_extractor_agent_nothing_runs(world: World) -> None:
    script = FakeScript()

    with pytest.raises(ExtractorUnavailableError, match="no extractor agent"):
        await extractor(world, None, script).extract("x", "codex")
    assert script.requests == []


async def test_a_failed_extraction_run_is_an_error_not_an_answer(world: World) -> None:
    script = FakeScript(subtype="error_max_turns", is_error=True, terminal_reason=None)

    with pytest.raises(ExtractorUnavailableError, match="failed"):
        await extractor(world, world.agent_id, script).extract("x", "codex")
