"""Login requests for agent tools, and the channels the owner is notified on (issue #195)."""

from datetime import datetime

from sqlalchemy import JSON, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base, enum_column
from labhq.db.enums import LoginStage


class LoginRequest(Base):
    """One pending login per tool and account. The tool keeps its credentials; labhq keeps none."""

    __tablename__ = "login_requests"
    __table_args__ = (
        Index("ix_login_requests_tool_account_stage", "tool", "account", "stage"),
        # The rate limit, enforced by the database: one pending login per tool and account.
        Index(
            "uq_login_requests_pending",
            "tool",
            "account",
            unique=True,
            sqlite_where=text("stage = 'pending'"),
            postgresql_where=text("stage = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # A key of `labhq.logins.login_tools`, not a closed vocabulary.
    tool: Mapped[str] = mapped_column(String(64))
    account: Mapped[str] = mapped_column(String(64), default="default")
    stage: Mapped[LoginStage] = mapped_column(
        enum_column(LoginStage, "login_stage"), default=LoginStage.PENDING
    )
    # The tool's own login link, shown to the owner only; the code that follows is never kept.
    url: Mapped[str | None] = mapped_column(Text)
    # Name of the private tmux session that runs the tool's login command.
    pane: Mapped[str | None] = mapped_column(String(64))
    # Set when the tool asked for a code to be pasted back; the owner pastes it in the terminal.
    awaits_code: Mapped[bool] = mapped_column(default=False)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]


class NotificationChannel(Base):
    """A place the owner is notified. Secrets are never here: they live in the data directory."""

    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    # A key of `labhq.channels.channel_kinds`.
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64), unique=True)
    # Non-secret settings (a server, a topic, a chat id), validated by the kind.
    config: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_test_ok: Mapped[bool | None]
    last_test_error: Mapped[str | None] = mapped_column(Text)
    last_tested_at: Mapped[datetime | None]
    created_at: Mapped[datetime]
