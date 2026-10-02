"""A new adapter joins by registration alone; the run engine needs no edit to use it."""

from collections.abc import AsyncIterator

from labhq.adapters import AdapterEvent, AdapterResult, RunRequest
from labhq.db.enums import RunStatus
from tests.runs.conftest import World
from tests.runs.helpers import costs_of, events_of, stored_run, use_adapter


class EchoAdapter:
    """Not a subclass of anything labhq ships: it satisfies the protocol and nothing more."""

    def __init__(self) -> None:
        self._prompt = ""

    async def start(self, request: RunRequest) -> None:
        self._prompt = request.prompt

    async def events(self) -> AsyncIterator[AdapterEvent]:
        yield AdapterEvent("echo", {"text": self._prompt})

    async def send(self, text: str) -> None:
        return None

    async def interrupt(self) -> None:
        return None

    def result(self) -> AdapterResult:
        return AdapterResult(subtype="success", is_error=False, session_id="echo-1", cost_usd=0.002)

    async def close(self) -> None:
        return None


async def test_a_registered_dummy_adapter_runs_through_the_engine(world: World) -> None:
    world.registry.register("echo", EchoAdapter)
    await use_adapter(world, "echo")

    run = await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="hi")

    stored = await stored_run(world, run.id)
    assert (stored.adapter, stored.status) == ("echo", RunStatus.SUCCEEDED)
    assert [(event.kind, event.payload) for event in await events_of(world, run.id)] == [
        ("echo", {"text": "hi"})
    ]
    assert [cost.cost_micros for cost in await costs_of(world, run.id)] == [2_000]
