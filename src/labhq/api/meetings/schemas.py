"""What the meetings UI receives, built from `labhq.meetings.minutes` and nothing else."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from labhq.db.enums import MeetingStatus, TaskStatus, TranscriptSource

MAX_MESSAGE_LENGTH = 4000


class MeetingItem(BaseModel):
    id: int
    kind: str
    project_id: int
    project_name: str
    status: MeetingStatus
    created_at: datetime
    # Absent until the meeting starts.
    started_at: datetime | None
    # The chat platform mirroring the meeting, if any; the meeting reads the same without.
    channel: str | None


class MeetingAttendee(BaseModel):
    id: int
    # None is the owner.
    agent_id: int | None
    name: str


class MeetingMessage(BaseModel):
    id: int
    source: TranscriptSource
    speaker: str
    # The speaking agent, so the UI can draw its avatar; None for the owner and the engine.
    agent_id: int | None
    text: str
    created_at: datetime


class MeetingDecisionEntry(BaseModel):
    id: int
    position: int
    text: str


class MeetingActionEntry(BaseModel):
    id: int
    text: str
    decision_id: int | None
    assignee_agent_id: int | None
    assignee_name: str | None
    task_id: int
    task_title: str
    task_status: TaskStatus


class MeetingDetail(MeetingItem):
    agenda: str
    end_reason: str | None
    ended_at: datetime | None
    participants: list[MeetingAttendee]
    messages: list[MeetingMessage]
    decisions: list[MeetingDecisionEntry]
    action_items: list[MeetingActionEntry]


class MeetingJoinBody(BaseModel):
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    ]
