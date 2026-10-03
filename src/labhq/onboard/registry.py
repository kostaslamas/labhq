"""Ordered step registry. A new onboarding step is one registration, never a runner edit."""

from collections.abc import Iterator
from dataclasses import dataclass

from labhq.onboard.base import Step


@dataclass(frozen=True)
class _Entry:
    order: int
    step: Step


class StepRegistry:
    """Steps run by ascending `order`; leave gaps so a later step can slot in between."""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def register(self, step: Step, *, order: int) -> None:
        if step.name in self._entries:
            raise ValueError(f"onboarding step {step.name!r} is already registered")
        self._entries[step.name] = _Entry(order, step)

    def __iter__(self) -> Iterator[Step]:
        entries = sorted(self._entries.values(), key=lambda entry: entry.order)
        return iter([entry.step for entry in entries])

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def copy(self) -> "StepRegistry":
        clone = StepRegistry()
        clone._entries = dict(self._entries)
        return clone
