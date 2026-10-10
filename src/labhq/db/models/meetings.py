"""Meetings: agenda, participants, transcript, decisions and action items (plan §2, §6).

The database is the source of truth for a meeting (plan §2.1); chat platforms only mirror it.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base, enum_column, micros_column
from labhq.db.enums import MeetingStatus, TranscriptSource


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        Index("ix_meetings_project_id_kind_created_at", "project_id", "kind", "created_at"),
        Index("ix_meetings_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    # A key of the meeting kind registry (standup, planning, ...), so not a closed vocabulary.
    kind: Mapped[str] = mapped_column(String(64))
    agenda: Mapped[str] = mapped_column(Text)
    status: Mapped[MeetingStatus] = mapped_column(
        enum_column(MeetingStatus, "meeting_status"), default=MeetingStatus.REQUESTED
    )
    # Why a meeting ended early or failed, e.g. "budget" or "invalid_minutes".
    end_reason: Mapped[str | None] = mapped_column(String(64))
    # The chat platform mirroring the meeting and its thread there, set by the chat bridge.
    channel_adapter: Mapped[str | None] = mapped_column(String(64))
    external_ref: Mapped[str | None] = mapped_column(String(255))
    facilitator_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approvals.id", ondelete="SET NULL"))
    # The CEO proposal a decision room discusses, as a `kind` ("report", "approval") and its id.
    # Plain columns, not a foreign key: the two kinds live in different tables.
    pinned_kind: Mapped[str | None] = mapped_column(String(32))
    pinned_id: Mapped[int | None]
    # What the owner was shown when the room's start was requested: the low and high end of the
    # forecast, whether it came from history or from constants, and the hard cap. A room
    # starts only with all four, and the cap is the one it was approved under.
    estimate_micros: Mapped[int | None] = micros_column(nullable=True)
    estimate_high_micros: Mapped[int | None] = micros_column(nullable=True)
    estimate_source: Mapped[str | None] = mapped_column(String(16))
    cost_cap_micros: Mapped[int | None] = micros_column(nullable=True)
    # When the thread said the room passed the high end of its estimate; set once.
    over_estimate_at: Mapped[datetime | None]
    # A live room is waiting for this agent's turn to finish, and why (cleared when it answers).
    waiting_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    waiting_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime]
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]


class MeetingParticipant(Base):
    __tablename__ = "meeting_participants"
    __table_args__ = (UniqueConstraint("meeting_id", "agent_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"))
    # NULL means the owner.
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    display_name: Mapped[str] = mapped_column(String(200))


class MeetingTranscriptEntry(Base):
    __tablename__ = "meeting_transcript_entries"
    # A message mirrored from a chat thread may arrive twice; the constraint records it once.
    __table_args__ = (
        UniqueConstraint("meeting_id", "external_ref"),
        Index("ix_meeting_transcript_entries_meeting_id_id", "meeting_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"))
    # NULL for a system entry, which no participant said.
    participant_id: Mapped[int | None] = mapped_column(
        ForeignKey("meeting_participants.id", ondelete="SET NULL")
    )
    source: Mapped[TranscriptSource] = mapped_column(
        enum_column(TranscriptSource, "transcript_source")
    )
    text: Mapped[str] = mapped_column(Text)
    # The run that produced the entry; NULL for the owner. Meeting cost sums these runs.
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    external_ref: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime]


class MeetingDecision(Base):
    __tablename__ = "meeting_decisions"
    __table_args__ = (UniqueConstraint("meeting_id", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int]


class MeetingActionItem(Base):
    __tablename__ = "meeting_action_items"
    __table_args__ = (Index("ix_meeting_action_items_meeting_id", "meeting_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"))
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("meeting_decisions.id", ondelete="SET NULL")
    )
    text: Mapped[str] = mapped_column(Text)
    assignee_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    # Plan §6: an action item creates a task and keeps the reference, so never NULL.
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), unique=True)
    # A decision room's item waits for the owner's approval before its task is assigned.
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approvals.id", ondelete="SET NULL"))
