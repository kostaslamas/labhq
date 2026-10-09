"""Federation: one labhq managing another as a remote manager (issue #188).

The upstream instance holds `federation_nodes` and `federation_orders`; the downstream one
holds `federation_invites`, `federation_inbound` and `federation_reports`. Both sets live in
every database so the same migration serves either role.
"""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base, enum_column, micros_column
from labhq.db.enums import OrderStage, ReportKind


class FederationNode(Base):
    """A downstream labhq the owner registered here; only the hash of its key is kept."""

    __tablename__ = "federation_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # Where the node lives, for the owner's reference.
    url: Mapped[str] = mapped_column(Text)
    # The node's A2A base URL. Set: orders go there. Unset: the node polls for them (#191).
    a2a_url: Mapped[str | None] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    manager_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    # Attached to every order sent to the node; the node refuses work beyond it.
    spend_cap_micros: Mapped[int | None] = micros_column(nullable=True)
    created_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    last_seen_at: Mapped[datetime | None]


class FederationInvite(Base):
    """A pairing key this instance printed once, for the owner to register upstream."""

    __tablename__ = "federation_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class FederationOrder(Base):
    """An order queued for a node: the words of a task given to its remote manager."""

    __tablename__ = "federation_orders"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_federation_orders_run_id"),
        Index("ix_federation_orders_node_id_status", "node_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("federation_nodes.id", ondelete="CASCADE"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    # The remote manager's run that queued it; a retry of that run queues nothing twice.
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    spend_cap_micros: Mapped[int | None] = micros_column(nullable=True)
    status: Mapped[OrderStage] = mapped_column(
        enum_column(OrderStage, "federation_order_status"), default=OrderStage.PENDING
    )
    # The last report sequence number applied, so a repeated report changes nothing.
    report_seq: Mapped[int] = mapped_column(default=0)
    # Over A2A: the node's task for this order and the last state it reported (#191).
    remote_task_id: Mapped[str | None] = mapped_column(String(100))
    remote_state: Mapped[str] = mapped_column(String(40), default="", server_default="")
    created_at: Mapped[datetime]
    delivered_at: Mapped[datetime | None]
    acknowledged_at: Mapped[datetime | None]


class FederationInbound(Base):
    """An order this instance received from its upstream, and the tasks that carry it out."""

    __tablename__ = "federation_inbound"

    id: Mapped[int] = mapped_column(primary_key=True)
    upstream_order_id: Mapped[int] = mapped_column(unique=True)
    upstream_name: Mapped[str] = mapped_column(String(100))
    # The invite whose key sent the order over A2A; empty for an order taken by polling.
    invite_id: Mapped[int | None] = mapped_column(
        ForeignKey("federation_invites.id", ondelete="SET NULL")
    )
    text: Mapped[str] = mapped_column(Text)
    spend_cap_micros: Mapped[int | None] = micros_column(nullable=True)
    # Root tasks the CEO delegated for this order; their subtrees count against the cap.
    task_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    report_seq: Mapped[int] = mapped_column(default=0)
    received_at: Mapped[datetime]


class FederationReport(Base):
    """A pointer-style report waiting to go up: a status and a reference on this instance."""

    __tablename__ = "federation_reports"
    __table_args__ = (
        UniqueConstraint("inbound_id", "seq", name="uq_federation_reports_inbound_id_seq"),
        Index("ix_federation_reports_delivered_at", "delivered_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inbound_id: Mapped[int] = mapped_column(ForeignKey("federation_inbound.id", ondelete="CASCADE"))
    seq: Mapped[int]
    status: Mapped[ReportKind] = mapped_column(enum_column(ReportKind, "federation_report_status"))
    summary: Mapped[str] = mapped_column(Text)
    ref: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime]
    delivered_at: Mapped[datetime | None]
