"""What the Call Center widget receives about decision rooms."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from labhq.api.meetings.schemas import MAX_MESSAGE_LENGTH
from labhq.db.enums import ApprovalStatus, MeetingStatus


class Waiting(BaseModel):
    agent_id: int
    agent_name: str
    reason: str
    # A tmux session the owner can interrupt with Esc (control keys, `/api/agents/{id}/keys`).
    can_interrupt: bool


class RoomItem(BaseModel):
    id: int
    status: MeetingStatus
    project_id: int
    project_name: str
    agenda: str
    pinned_kind: str | None
    pinned_id: int | None
    # Shown with the approval of the start; None once it is no longer a guess.
    estimate_micros: int | None
    approval_id: int | None
    approval_status: ApprovalStatus | None
    turns_used: int
    turn_cap: int
    waiting: Waiting | None
    end_reason: str | None
    created_at: datetime
    ended_at: datetime | None


class RoomMessage(BaseModel):
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    ]


class DecidedAction(BaseModel):
    text: str
    approval_id: int | None
    # Waits for the owner while pending; the task is assigned only once it is executed.
    approval_status: ApprovalStatus | None


class Decided(BaseModel):
    meeting_id: int
    pinned_kind: str
    pinned_id: int
    decisions: list[str]
    actions: list[DecidedAction]
    ended_at: datetime
