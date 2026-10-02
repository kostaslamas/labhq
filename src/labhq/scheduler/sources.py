"""The five wakeup sources (plan §7) as a registry `source -> handler`.

A trigger names an event; its handler resolves who wakes, for which task, and the
idempotency key. The key derives from the event's identity, so a retried trigger maps to
the same key and enqueues nothing new. A new source is a new registration.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import ensure_utc
from labhq.db.enums import ApprovalStatus, WakeupSource
from labhq.db.models import Approval, Comment, Task


@dataclass(frozen=True, slots=True)
class WakeupSpec:
    """One agent to wake: the row `enqueue` writes, before idempotency and coalescing."""

    agent_id: int
    task_id: int | None
    source: WakeupSource
    reason: str
    idempotency_key: str


class Trigger(Protocol):
    source: ClassVar[WakeupSource]


@dataclass(frozen=True, slots=True)
class TimerWakeup:
    source: ClassVar[WakeupSource] = WakeupSource.TIMER
    agent_id: int
    due_at: datetime
    reason: str = "scheduled"


@dataclass(frozen=True, slots=True)
class AssignmentWakeup:
    source: ClassVar[WakeupSource] = WakeupSource.ASSIGNMENT
    task_id: int


@dataclass(frozen=True, slots=True)
class CommentWakeup:
    """Wakes every agent the comment mentions, except its author."""

    source: ClassVar[WakeupSource] = WakeupSource.COMMENT
    comment_id: int


@dataclass(frozen=True, slots=True)
class ApprovalResolvedWakeup:
    """Wakes the agent that asked for the approval, once per decision."""

    source: ClassVar[WakeupSource] = WakeupSource.APPROVAL_RESOLVED
    approval_id: int


@dataclass(frozen=True, slots=True)
class MeetingWakeup:
    # Meetings arrive in Phase 3; until then the caller names the meeting by reference.
    source: ClassVar[WakeupSource] = WakeupSource.MEETING
    agent_id: int
    meeting_ref: str
    reason: str = "meeting"
    task_id: int | None = None


WakeupHandler = Callable[[AsyncSession, Any], Awaitable[list[WakeupSpec]]]


class UnknownWakeupSourceError(LookupError):
    pass


class WakeupSources:
    def __init__(self) -> None:
        self._handlers: dict[WakeupSource, WakeupHandler] = {}

    def register(
        self, source: WakeupSource, handler: WakeupHandler, *, replace: bool = False
    ) -> None:
        if source in self._handlers and not replace:
            raise ValueError(f"wakeup source {source!r} is already registered")
        self._handlers[source] = handler

    async def specs_for(self, session: AsyncSession, trigger: Trigger) -> list[WakeupSpec]:
        try:
            handler = self._handlers[trigger.source]
        except KeyError:
            raise UnknownWakeupSourceError(f"no handler for {trigger.source!r}") from None
        return await handler(session, trigger)

    def sources(self) -> list[WakeupSource]:
        return sorted(self._handlers)

    def copy(self) -> "WakeupSources":
        clone = WakeupSources()
        clone._handlers = dict(self._handlers)
        return clone


def _instant(value: datetime) -> str:
    return ensure_utc(value).isoformat()


async def _timer(_session: AsyncSession, trigger: TimerWakeup) -> list[WakeupSpec]:
    key = f"timer:agent:{trigger.agent_id}:{_instant(trigger.due_at)}"
    return [WakeupSpec(trigger.agent_id, None, WakeupSource.TIMER, trigger.reason, key)]


async def _assignment(session: AsyncSession, trigger: AssignmentWakeup) -> list[WakeupSpec]:
    task = await session.get_one(Task, trigger.task_id)
    if task.assignee_id is None:
        return []
    # `updated_at` tells one assignment from a later reassignment to the same agent.
    key = f"assignment:task:{task.id}:agent:{task.assignee_id}:{_instant(task.updated_at)}"
    reason = f"assigned task {task.id}: {task.title}"
    return [WakeupSpec(task.assignee_id, task.id, WakeupSource.ASSIGNMENT, reason, key)]


async def _comment(session: AsyncSession, trigger: CommentWakeup) -> list[WakeupSpec]:
    comment = await session.get_one(Comment, trigger.comment_id)
    author = comment.author_agent_id
    mentioned = dict.fromkeys(int(agent_id) for agent_id in comment.mentions if agent_id != author)
    return [
        WakeupSpec(
            agent_id,
            comment.task_id,
            WakeupSource.COMMENT,
            f"mentioned in comment {comment.id} on task {comment.task_id}",
            f"comment:{comment.id}:agent:{agent_id}",
        )
        for agent_id in mentioned
    ]


async def _approval(session: AsyncSession, trigger: ApprovalResolvedWakeup) -> list[WakeupSpec]:
    approval = await session.get_one(Approval, trigger.approval_id)
    agent_id = approval.requested_by_agent_id
    if agent_id is None or approval.status is ApprovalStatus.PENDING:
        return []
    return [
        WakeupSpec(
            agent_id,
            approval.task_id,
            WakeupSource.APPROVAL_RESOLVED,
            f"approval {approval.id} ({approval.type}) is {approval.status}",
            f"approval:{approval.id}:{approval.status}",
        )
    ]


async def _meeting(_session: AsyncSession, trigger: MeetingWakeup) -> list[WakeupSpec]:
    key = f"meeting:{trigger.meeting_ref}:agent:{trigger.agent_id}"
    return [
        WakeupSpec(trigger.agent_id, trigger.task_id, WakeupSource.MEETING, trigger.reason, key)
    ]


default_sources = WakeupSources()
default_sources.register(WakeupSource.TIMER, _timer)
default_sources.register(WakeupSource.ASSIGNMENT, _assignment)
default_sources.register(WakeupSource.COMMENT, _comment)
default_sources.register(WakeupSource.APPROVAL_RESOLVED, _approval)
default_sources.register(WakeupSource.MEETING, _meeting)
