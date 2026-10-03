"""Hosts, their metric samples, health rules and the incidents rules open."""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base, enum_column
from labhq.db.enums import HealthRuleAction, HostStatus, IncidentStatus


class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    address: Mapped[str | None] = mapped_column(String(255))
    ssh_user: Mapped[str | None] = mapped_column(String(64))
    # Runs approved interventions; without one, the engine refuses to touch the host.
    intervention_user: Mapped[str | None] = mapped_column(String(64))
    # The machine labhq runs on; the collector creates this row on first run.
    is_local: Mapped[bool] = mapped_column(default=False)
    status: Mapped[HostStatus] = mapped_column(
        enum_column(HostStatus, "host_status"), default=HostStatus.UNKNOWN
    )
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class HealthSample(Base):
    __tablename__ = "health_samples"
    __table_args__ = (
        Index("ix_health_samples_host_id_metric_sampled_at", "host_id", "metric", "sampled_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(String(128))
    # What the metric is about when a host has several: a mount point, a sensor.
    subject: Mapped[str | None] = mapped_column(String(255))
    value: Mapped[float]
    sampled_at: Mapped[datetime]


class HealthRule(Base):
    __tablename__ = "health_rules"
    __table_args__ = (Index("ix_health_rules_enabled", "enabled"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # A registry key (threshold, ...), so new rule types need no migration.
    type: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    action: Mapped[HealthRuleAction] = mapped_column(
        enum_column(HealthRuleAction, "health_rule_action"), default=HealthRuleAction.NOTIFY
    )
    # NULL applies the rule to every host.
    host_id: Mapped[int | None] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        # A repeated violation must not open a second incident for the same rule and host.
        Index(
            "uq_incidents_rule_id_host_id_open",
            "rule_id",
            "host_id",
            unique=True,
            sqlite_where=text("status = 'open'"),
        ),
        Index("ix_incidents_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("health_rules.id", ondelete="CASCADE"))
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    status: Mapped[IncidentStatus] = mapped_column(
        enum_column(IncidentStatus, "incident_status"), default=IncidentStatus.OPEN
    )
    # The ticket, when the rule's action opens one.
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    opened_at: Mapped[datetime]
    resolved_at: Mapped[datetime | None]
