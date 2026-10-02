"""Turns rule evaluations into incidents: one open incident per rule and host at most."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.enums import IncidentStatus
from labhq.db.models import HealthRule, Host, Incident
from labhq.health.rules import (
    Evaluation,
    RuleContext,
    RuleRegistry,
    UnknownRuleTypeError,
    registry,
)

logger = logging.getLogger(__name__)


class Transition(StrEnum):
    OPENED = "opened"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class IncidentChange:
    """What changed in one pass, for whoever notifies (Call Center, `#infra`, later phases)."""

    transition: Transition
    incident: Incident
    rule: HealthRule


async def _open_incident(session: AsyncSession, rule: HealthRule, host: Host) -> Incident | None:
    return await session.scalar(
        select(Incident).where(
            Incident.rule_id == rule.id,
            Incident.host_id == host.id,
            Incident.status == IncidentStatus.OPEN,
        )
    )


async def apply_evaluation(
    session: AsyncSession,
    clock: Clock,
    rule: HealthRule,
    host: Host,
    evaluation: Evaluation,
) -> IncidentChange | None:
    """Open on violation, resolve on recovery, and do nothing while the state holds."""
    current = await _open_incident(session, rule, host)
    if evaluation.violated and current is None:
        incident = Incident(
            rule_id=rule.id, host_id=host.id, details=evaluation.details, opened_at=clock.now()
        )
        session.add(incident)
        await session.flush()
        return IncidentChange(Transition.OPENED, incident, rule)
    if not evaluation.violated and current is not None:
        current.status = IncidentStatus.RESOLVED
        current.resolved_at = clock.now()
        await session.flush()
        return IncidentChange(Transition.RESOLVED, current, rule)
    return None


async def _hosts_for(session: AsyncSession, rule: HealthRule) -> Sequence[Host]:
    query = select(Host).order_by(Host.id)
    if rule.host_id is not None:
        query = query.where(Host.id == rule.host_id)
    return (await session.scalars(query)).all()


async def evaluate_rules(
    session: AsyncSession, clock: Clock, rules: RuleRegistry = registry
) -> list[IncidentChange]:
    """Evaluate every enabled rule on its hosts. The caller owns the transaction."""
    now = clock.now()
    enabled = await session.scalars(
        select(HealthRule).where(HealthRule.enabled.is_(True)).order_by(HealthRule.id)
    )
    changes = []
    for rule in enabled.all():
        for host in await _hosts_for(session, rule):
            try:
                evaluation = await rules.evaluate(RuleContext(session, rule, host, now))
            except (UnknownRuleTypeError, ValidationError):
                # Rules are data an agent may write; one bad row must not stop the others.
                logger.warning("skipping health rule %s (%s)", rule.id, rule.type, exc_info=True)
                break
            change = await apply_evaluation(session, clock, rule, host, evaluation)
            if change is not None:
                changes.append(change)
    return changes
