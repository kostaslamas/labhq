"""`source -> handler`: what each wakeup source requires and how it briefs the agent.

A new source is a new registration. The scheduler never branches on the source itself.
"""

from dataclasses import dataclass
from typing import Protocol

from labhq.db.enums import WakeupSource
from labhq.db.models import Task, WakeupRequest


class InvalidWakeupError(ValueError):
    pass


class SourceHandler(Protocol):
    def validate(self, task_id: int | None) -> None: ...

    def prompt(self, request: WakeupRequest, task: Task | None) -> str: ...


@dataclass(frozen=True)
class TemplateHandler:
    """A handler described by data: whether a task is required and the opening line."""

    requires_task: bool
    opening: str

    def validate(self, task_id: int | None) -> None:
        if self.requires_task and task_id is None:
            raise InvalidWakeupError(f"{self.opening!r} wakeups need a task")

    def prompt(self, request: WakeupRequest, task: Task | None) -> str:
        lines = [self.opening]
        if request.reason:
            lines.append(f"Reason: {request.reason}")
        if request.coalesced_count:
            lines.append(f"{request.coalesced_count} further wakeups arrived meanwhile.")
        if task is not None:
            lines.append(f"Task #{task.id}: {task.title}")
            if task.description:
                lines.append(task.description)
        return "\n".join(lines)


class UnknownSourceError(LookupError):
    pass


class SourceRegistry:
    def __init__(self) -> None:
        self._handlers: dict[WakeupSource, SourceHandler] = {}

    def register(
        self, source: WakeupSource, handler: SourceHandler, *, replace: bool = False
    ) -> None:
        if source in self._handlers and not replace:
            raise ValueError(f"source {source!r} is already registered")
        self._handlers[source] = handler

    def handler(self, source: WakeupSource) -> SourceHandler:
        try:
            return self._handlers[source]
        except KeyError:
            raise UnknownSourceError(f"no handler registered for {source!r}") from None

    def sources(self) -> list[WakeupSource]:
        return sorted(self._handlers)


default_sources = SourceRegistry()
default_sources.register(WakeupSource.TIMER, TemplateHandler(False, "Scheduled check-in."))
default_sources.register(
    WakeupSource.ASSIGNMENT, TemplateHandler(True, "A task was assigned to you.")
)
default_sources.register(
    WakeupSource.COMMENT, TemplateHandler(True, "You were mentioned in a task comment.")
)
default_sources.register(
    WakeupSource.APPROVAL_RESOLVED, TemplateHandler(False, "An approval you asked for resolved.")
)
default_sources.register(WakeupSource.MEETING, TemplateHandler(False, "A meeting needs you."))
