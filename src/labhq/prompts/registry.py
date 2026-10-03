"""System prompt sections as data: a new section is a new registration, never an assembler edit.

Each section builds its text from the agent and its task, or returns None to stay out. The
assembler joins the sections by position, so the order is fixed whoever registers first.
"""

from collections.abc import Callable
from dataclasses import dataclass

from labhq.db.models import Agent, Task

type SectionBuilder = Callable[[Agent, Task | None], str | None]


class DuplicateSectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Section:
    name: str
    # Lower comes first; ties fall back to the name, so the order never depends on imports.
    position: int
    builder: SectionBuilder


class PromptRegistry:
    def __init__(self) -> None:
        self._sections: dict[str, Section] = {}

    def register(
        self, name: str, builder: SectionBuilder, *, position: int, replace: bool = False
    ) -> None:
        if name in self._sections and not replace:
            raise DuplicateSectionError(name)
        self._sections[name] = Section(name, position, builder)

    def sections(self) -> list[Section]:
        return sorted(self._sections.values(), key=lambda section: (section.position, section.name))

    def assemble(self, agent: Agent, task: Task | None) -> str | None:
        """The text appended to the adapter's system prompt, or None when no section speaks."""
        parts = [
            text.strip()
            for section in self.sections()
            if (text := section.builder(agent, task)) is not None and text.strip()
        ]
        return "\n\n".join(parts) or None

    def copy(self) -> "PromptRegistry":
        clone = PromptRegistry()
        clone._sections = dict(self._sections)
        return clone
