"""Listeners for meeting events, keyed by name. It ships empty; the chat bridge registers one.

A listener only observes. One that raises is logged and skipped, so a chat outage never
stops a meeting: the database stays the source of truth (plan §2.1).
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)


class MeetingEventKind(StrEnum):
    STARTED = "started"
    ENTRY_ADDED = "entry_added"
    ENDED = "ended"


@dataclass(frozen=True)
class MeetingEvent:
    kind: MeetingEventKind
    meeting_id: int
    # The transcript entry, for `entry_added`.
    entry_id: int | None = None


Listener = Callable[[MeetingEvent], Awaitable[None]]


class MeetingListeners:
    def __init__(self) -> None:
        self._listeners: dict[str, Listener] = {}

    def register(self, name: str, listener: Listener, *, replace: bool = False) -> None:
        if name in self._listeners and not replace:
            raise ValueError(f"meeting listener {name!r} is already registered")
        self._listeners[name] = listener

    def unregister(self, name: str) -> None:
        self._listeners.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self._listeners)

    async def emit(self, event: MeetingEvent) -> None:
        for name, listener in list(self._listeners.items()):
            try:
                await listener(event)
            except Exception:
                logger.exception("meeting listener %r failed on %s", name, event.kind)


default_listeners = MeetingListeners()
