"""Wakeups, runs, their event stream, cost and resumable sessions."""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base, enum_column, micros_column
from labhq.db.enums import RunStatus, WakeupSource, WakeupStatus


class WakeupRequest(Base):
    __tablename__ = "wakeup_requests"
    __table_args__ = (Index("ix_wakeup_requests_agent_id_status", "agent_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    source: Mapped[WakeupSource] = mapped_column(enum_column(WakeupSource, "wakeup_source"))
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[WakeupStatus] = mapped_column(
        enum_column(WakeupStatus, "wakeup_status"), default=WakeupStatus.PENDING
    )
    coalesced_count: Mapped[int] = mapped_column(default=0)
    # Unique so a retried enqueue finds the existing request instead of adding work.
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_agent_id_status", "agent_id", "status"),
        Index("ix_runs_task_id", "task_id"),
        # The reaper scans running runs by heartbeat age.
        Index("ix_runs_status_heartbeat_at", "status", "heartbeat_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    adapter: Mapped[str] = mapped_column(String(64))
    status: Mapped[RunStatus] = mapped_column(
        enum_column(RunStatus, "run_status"), default=RunStatus.QUEUED
    )
    session_id_before: Mapped[str | None] = mapped_column(String(128))
    session_id_after: Mapped[str | None] = mapped_column(String(128))
    usage: Mapped[dict[str, Any] | None]
    # Terminal details from the adapter, e.g. subtype and terminal_reason.
    exit: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    seq: Mapped[int]
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime]


class CostEvent(Base):
    __tablename__ = "cost_events"
    __table_args__ = (
        Index("ix_cost_events_agent_id_created_at", "agent_id", "created_at"),
        Index("ix_cost_events_project_id_created_at", "project_id", "created_at"),
        Index("ix_cost_events_run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    cost_micros: Mapped[int] = micros_column(nullable=False)
    model: Mapped[str | None] = mapped_column(String(128))
    # Token counts let the token-economy A/B checks compare runs without the cost model.
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_input_tokens: Mapped[int] = mapped_column(default=0)
    cache_creation_input_tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime]


class AgentTaskSession(Base):
    __tablename__ = "agent_task_sessions"
    __table_args__ = (UniqueConstraint("agent_id", "task_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    # tmux sessions include their CLI kind, e.g. tmux:codex, to prevent cross-kind resume.
    adapter: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(128))
    # Sessions are stored per working directory, so resume needs the same cwd.
    cwd: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
