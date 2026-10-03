"""Usage readings in units other than USD: plan percentages, tokens (ADR 0003).

A USD reading becomes a `cost_events` row instead (ADR 0002). A reading that failed its
checks is kept with `error` set and no value, so a failure is never read as zero.
"""

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base


class UsageReading(Base):
    __tablename__ = "usage_readings"
    __table_args__ = (
        # The plan cap reads the latest reading per agent kind and window.
        Index("ix_usage_readings_agent_kind_unit_window", "agent_kind", "unit", "window"),
        Index("ix_usage_readings_run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    # The CLI the reading is about, e.g. `claude-code`. Plan windows are per account and CLI.
    agent_kind: Mapped[str] = mapped_column(String(64))
    # Where the reading came from: `statusline`, `screen` or `limit_notice`.
    source: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str | None] = mapped_column(String(32))
    window: Mapped[str | None] = mapped_column(String(32))
    value: Mapped[float | None] = mapped_column(Float)
    limit_value: Mapped[float | None] = mapped_column(Float)
    resets_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]
