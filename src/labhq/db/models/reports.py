"""What the global CEO reports to the owner, kept beside the CEO chat (issue #170)."""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base


class CeoReport(Base):
    __tablename__ = "ceo_reports"
    __table_args__ = (Index("ix_ceo_reports_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    # Free references the CEO names, such as "T12" or a project; shown, never parsed.
    refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Set when the report asks the owner to accept or return this root task.
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    created_at: Mapped[datetime]
