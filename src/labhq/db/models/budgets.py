"""Budget warnings: the 80% crossing, recorded once per scope and budget period."""

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base, enum_column, micros_column
from labhq.db.enums import BudgetScope


class BudgetWarning(Base):
    __tablename__ = "budget_warnings"
    # The constraint, not the caller, makes the warning happen once per period.
    __table_args__ = (UniqueConstraint("scope", "scope_id", "period_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[BudgetScope] = mapped_column(enum_column(BudgetScope, "budget_scope"))
    # An agent or project id, depending on `scope`. No foreign key: the row is an audit
    # record and must not vanish or block when its subject is deleted.
    scope_id: Mapped[int]
    period_start: Mapped[datetime]
    spent_micros: Mapped[int] = micros_column(nullable=False)
    budget_micros: Mapped[int] = micros_column(nullable=False)
    created_at: Mapped[datetime]
