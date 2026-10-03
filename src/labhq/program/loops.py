"""Background duties as registrations: a name, the setting that paces it, a step factory.

A new duty is a new `register` call. `run_loop` is the only place that decides what a
failing pass means: it is logged and retried on the next tick, never fatal.
"""

import logging
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass

from labhq.clock import Clock
from labhq.program.settings import ProgramSettings

log = logging.getLogger(__name__)

type Step = Callable[[], Awaitable[object]]


@dataclass(frozen=True)
class LoopSpec[S]:
    name: str
    # A field of `ProgramSettings`, so the interval is configuration, not a constant.
    interval_setting: str
    build: Callable[[S], Step]

    def interval(self, settings: ProgramSettings) -> float:
        return float(getattr(settings, self.interval_setting))


class LoopRegistry[S]:
    def __init__(self) -> None:
        self._specs: dict[str, LoopSpec[S]] = {}

    def register(self, name: str, interval_setting: str, build: Callable[[S], Step]) -> None:
        if name in self._specs:
            raise ValueError(f"loop {name!r} is already registered")
        if interval_setting not in ProgramSettings.model_fields:
            raise ValueError(f"unknown interval setting {interval_setting!r}")
        self._specs[name] = LoopSpec(name, interval_setting, build)

    def __iter__(self) -> Iterator[LoopSpec[S]]:
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)


async def run_loop(name: str, interval: float, step: Step, clock: Clock) -> None:
    """Run `step`, wait `interval` on the clock, repeat until cancelled."""
    while True:
        try:
            await step()
        except Exception:
            # Cancellation is a BaseException and passes through; anything else is one bad tick.
            log.exception("loop %s failed; retrying in %ss", name, interval)
        await clock.sleep(interval)
