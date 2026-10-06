"""Call Center: calls, owner requests, wording proposals, deliveries, agent questions and the
notification outbox."""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base, enum_column
from labhq.db.enums import (
    CallRequestStatus,
    CallStatus,
    NotificationStatus,
    ProposalStatus,
    QuestionStatus,
)


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = (Index("ix_calls_status_last_activity_at", "status", "last_activity_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    session_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[CallStatus] = mapped_column(
        enum_column(CallStatus, "call_status"), default=CallStatus.OPEN
    )
    opened_at: Mapped[datetime]
    last_activity_at: Mapped[datetime]
    closed_at: Mapped[datetime | None]


class CallRequest(Base):
    __tablename__ = "call_requests"
    __table_args__ = (Index("ix_call_requests_call_id_status", "call_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"))
    # Client-visible ticket handle; unique so a retried submit cannot create a second request.
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    # The owner's words, verbatim: nothing downstream may rewrite them.
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[CallRequestStatus] = mapped_column(
        enum_column(CallRequestStatus, "call_request_status"), default=CallRequestStatus.PENDING
    )
    reply: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]
    answered_at: Mapped[datetime | None]


class WordingProposal(Base):
    """A clearer wording of one owner request, sent to the CEO only once the owner confirms."""

    __tablename__ = "wording_proposals"
    __table_args__ = (Index("ix_wording_proposals_request_id", "request_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"))
    # The owner's original words stay on this request; the proposal never replaces them.
    request_id: Mapped[str] = mapped_column(ForeignKey("call_requests.request_id"))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[ProposalStatus] = mapped_column(
        enum_column(ProposalStatus, "proposal_status"), default=ProposalStatus.PENDING
    )
    # Only requests stored after this one can answer the proposal: the owner heard it first.
    after_request_pk: Mapped[int]
    decided_by_request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime]
    decided_at: Mapped[datetime | None]


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        Index("ix_deliveries_call_id", "call_id"),
        Index("ix_deliveries_recipient_agent_id", "recipient_agent_id"),
        Index("ix_deliveries_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"))
    request_id: Mapped[str] = mapped_column(ForeignKey("call_requests.request_id"))
    recipient_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    interrupted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime]


class AgentQuestion(Base):
    __tablename__ = "agent_questions"
    __table_args__ = (
        Index("ix_agent_questions_status_created_at", "status", "created_at"),
        Index("ix_agent_questions_agent_id", "agent_id"),
        Index("ix_agent_questions_task_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(Text)
    # Hash of agent, task and question text: re-reading a status file inserts nothing new.
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[QuestionStatus] = mapped_column(
        enum_column(QuestionStatus, "question_status"), default=QuestionStatus.PENDING
    )
    answer: Mapped[str | None] = mapped_column(Text)
    answer_request_id: Mapped[str | None] = mapped_column(String(64))
    answered_at: Mapped[datetime | None]
    created_at: Mapped[datetime]


class StatusUpdate(Base):
    __tablename__ = "status_updates"
    __table_args__ = (
        Index("ix_status_updates_agent_id_observed_at", "agent_id", "observed_at"),
        Index("ix_status_updates_task_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    fields: Mapped[dict[str, Any]] = mapped_column(default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime]


class Notification(Base):
    """Outbox row: written in the same transaction as the event, sent later by the notifier."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_status_next_attempt_at", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # A registry key (approval_requested, agent_question, test), not a closed vocabulary.
    kind: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    click_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[NotificationStatus] = mapped_column(
        enum_column(NotificationStatus, "notification_status"),
        default=NotificationStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime]
    sent_at: Mapped[datetime | None]
