import asyncio
import logging

import pytest

from labhq.program import LoopRegistry, ProgramSettings, run_loop
from tests.program.conftest import Passes, SteppedClock


async def test_each_registered_loop_runs_at_its_own_interval(stepped: SteppedClock) -> None:
    seen: dict[str, list[float]] = {"fast": [], "slow": []}
    start = stepped.now()

    def recorder(name: str):
        async def step() -> None:
            seen[name].append((stepped.now() - start).total_seconds())

        return lambda _services: step

    registry: LoopRegistry[None] = LoopRegistry()
    registry.register("fast", "scheduler_interval_seconds", recorder("fast"))
    registry.register("slow", "notify_interval_seconds", recorder("slow"))
    settings = ProgramSettings(scheduler_interval_seconds=2, notify_interval_seconds=5)

    tasks = [
        asyncio.create_task(run_loop(spec.name, spec.interval(settings), spec.build(None), stepped))
        for spec in registry
    ]
    await stepped.yield_to_loop()
    for _ in range(10):
        await stepped.tick(1)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    assert seen["fast"] == [0, 2, 4, 6, 8, 10]
    assert seen["slow"] == [0, 5, 10]


async def test_a_loop_that_raises_runs_again_and_leaves_the_others_alone(
    stepped: SteppedClock, caplog: pytest.LogCaptureFixture
) -> None:
    passes = Passes()
    calls = {"flaky": 0, "steady": 0}

    async def flaky() -> None:
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            raise RuntimeError("first pass fails")

    async def steady() -> None:
        calls["steady"] += 1

    tasks = [
        asyncio.create_task(run_loop("flaky", 3, passes.watch("flaky", flaky), stepped)),
        asyncio.create_task(run_loop("steady", 3, passes.watch("steady", steady), stepped)),
    ]
    with caplog.at_level(logging.ERROR, logger="labhq.program.loops"):
        await passes.reached("flaky", 1)
        await stepped.tick(3)
        await passes.reached("flaky", 2)
        await passes.reached("steady", 2)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    assert calls == {"flaky": 2, "steady": 2}
    assert "loop flaky failed" in caplog.text


async def noop() -> None:
    return None


def test_a_loop_name_registers_once_against_a_real_setting() -> None:
    registry: LoopRegistry[None] = LoopRegistry()
    registry.register("a", "scheduler_interval_seconds", lambda _: noop)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="already registered"):
        registry.register("a", "scheduler_interval_seconds", lambda _: noop)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown interval setting"):
        registry.register("b", "no_such_setting", lambda _: noop)  # type: ignore[arg-type]
