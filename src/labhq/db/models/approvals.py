"""Approvals: agents request, a human decides, the engine executes."""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base, enum_column
from labhq.db.enums import ApprovalStatus, RiskClass


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_status_created_at", "status", "created_at"),
        Index("ix_approvals_task_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # The action type is a registry key (push, merge, ...), so it is not a closed vocabulary.
    type: Mapped[str] = mapped_column(String(64))
    risk_class: Mapped[RiskClass] = mapped_column(enum_column(RiskClass, "risk_class"))
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_column(ApprovalStatus, "approval_status"), default=ApprovalStatus.PENDING
    )
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    requested_by_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None]
    confirmation_kind: Mapped[str | None] = mapped_column(String(64))
    decision_note: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None]
    execution: Mapped[dict[str, Any] | None]
    # Where an external approval gate stands for this approval: its name, the request id it
    # returned, and why it was left pending. Never a credential.
    gate: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime]
