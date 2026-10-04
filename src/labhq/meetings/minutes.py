"""A meeting as its readers see it: the MCP tool, the CLI and the Phase 4 UI.

Read from the database alone, so a meeting reads the same with every chat platform
disconnected (plan §2.1).
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.enums import MeetingStatus, TaskStatus, TranscriptSource
from labhq.db.models import (
    Meeting,
    MeetingActionItem,
    MeetingDecision,
    MeetingParticipant,
    MeetingTranscriptEntry,
    Task,
)
from labhq.meetings.cost import meeting_cost_micros


@dataclass(frozen=True)
class ParticipantView:
    id: int
    agent_id: int | None
    display_name: str


@dataclass(frozen=True)
class EntryView:
    id: int
    speaker: str
    source: TranscriptSource
    text: str
    run_id: int | None
    external_ref: str | None
    created_at: datetime
    # Who said it; None for a system entry. The UI finds the speaker's agent through this.
    participant_id: int | None = None


@dataclass(frozen=True)
class DecisionView:
    id: int
    position: int
    text: str


@dataclass(frozen=True)
class ActionItemView:
    id: int
    text: str
    decision_id: int | None
    assignee_agent_id: int | None
    task_id: int
    task_title: str
    task_status: TaskStatus


@dataclass(frozen=True)
class MinutesView:
    meeting_id: int
    project_id: int
    kind: str
    agenda: str
    status: MeetingStatus
    end_reason: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    participants: tuple[ParticipantView, ...]
    transcript: tuple[EntryView, ...]
    decisions: tuple[DecisionView, ...]
    action_items: tuple[ActionItemView, ...]
    cost_micros: int


class MeetingNotFoundError(LookupError):
    pass


async def read_minutes(db: AsyncSession, meeting_id: int) -> MinutesView:
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise MeetingNotFoundError(f"no meeting {meeting_id}")
    participants = list(
        await db.scalars(
            select(MeetingParticipant)
            .where(MeetingParticipant.meeting_id == meeting_id)
            .order_by(MeetingParticipant.id)
        )
    )
    names = {participant.id: participant.display_name for participant in participants}
    entries = await db.scalars(
        select(MeetingTranscriptEntry)
        .where(MeetingTranscriptEntry.meeting_id == meeting_id)
        .order_by(MeetingTranscriptEntry.id)
    )
    decisions = await db.scalars(
        select(MeetingDecision)
        .where(MeetingDecision.meeting_id == meeting_id)
        .order_by(MeetingDecision.position)
    )
    items = await db.execute(
        select(MeetingActionItem, Task.title, Task.status)
        .join(Task, MeetingActionItem.task_id == Task.id)
        .where(MeetingActionItem.meeting_id == meeting_id)
        .order_by(MeetingActionItem.id)
    )
    return MinutesView(
        meeting_id=meeting.id,
        project_id=meeting.project_id,
        kind=meeting.kind,
        agenda=meeting.agenda,
        status=meeting.status,
        end_reason=meeting.end_reason,
        created_at=meeting.created_at,
        started_at=meeting.started_at,
        ended_at=meeting.ended_at,
        participants=tuple(ParticipantView(p.id, p.agent_id, p.display_name) for p in participants),
        transcript=tuple(
            EntryView(
                id=entry.id,
                speaker=names.get(entry.participant_id or 0, entry.source.value),
                source=entry.source,
                text=entry.text,
                run_id=entry.run_id,
                external_ref=entry.external_ref,
                created_at=entry.created_at,
                participant_id=entry.participant_id,
            )
            for entry in entries
        ),
        decisions=tuple(DecisionView(d.id, d.position, d.text) for d in decisions),
        action_items=tuple(
            ActionItemView(
                id=item.id,
                text=item.text,
                decision_id=item.decision_id,
                assignee_agent_id=item.assignee_agent_id,
                task_id=item.task_id,
                task_title=title,
                task_status=status,
            )
            for item, title, status in items
        ),
        cost_micros=await meeting_cost_micros(db, meeting_id),
    )
