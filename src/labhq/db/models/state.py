"""Small runtime switches the owner changes while the program runs."""

from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base


class ProgramState(Base):
    __tablename__ = "program_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime]
