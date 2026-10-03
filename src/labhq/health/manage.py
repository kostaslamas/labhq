"""Rule management: what an agent, the CLI and the Phase 4 UI call to add and tune rules.

Every rule carries a reason, so whoever reads it later knows why it exists (plan §2.2), and
its params are validated by its type before the row lands. Functions flush; the caller owns
the transaction.
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Imported for its registrations: the rule types beyond `threshold`.
import labhq.health.rule_types  # noqa: F401
from labhq.clock import Clock
from labhq.db.enums import HealthRuleAction
from labhq.db.models import HealthRule, Host, Incident
from labhq.health.rules import RuleRegistry, UnknownRuleTypeError, registry

logger = logging.getLogger(__name__)

NAME_LENGTH = 200


class RuleError(ValueError):
    """A rule request that cannot be carried out as given; the message says why."""


@dataclass(frozen=True)
class RuleView:
    rule: HealthRule
    # The rule's most recent incident, open or resolved: its latest observed result.
    latest: Incident | None


def _required(value: str, what: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise RuleError(f"a rule needs a non-empty {what}")
    return stripped


def _validated(rules: RuleRegistry, rule_type: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return rules.validate_params(rule_type, params)
    except UnknownRuleTypeError:
        known = ", ".join(sorted(rules.types()))
        raise RuleError(f"no rule type {rule_type!r}; known: {known}") from None


def _default_name(rule_type: str, params: dict[str, Any]) -> str:
    return f"{rule_type} {json.dumps(params, sort_keys=True)}"[:NAME_LENGTH]


async def find_rule(db: AsyncSession, rule_id: int) -> HealthRule:
    rule = await db.get(HealthRule, rule_id)
    if rule is None:
        raise RuleError(f"no rule {rule_id}")
    return rule


async def add_rule(
    db: AsyncSession,
    clock: Clock,
    *,
    rule_type: str,
    params: dict[str, Any],
    action: HealthRuleAction,
    reason: str,
    created_by: str,
    name: str | None = None,
    host_id: int | None = None,
    rules: RuleRegistry = registry,
) -> HealthRule:
    """Add an enabled rule. Raises `RuleError`, or `ValidationError` for bad params."""
    reason = _required(reason, "reason")
    created_by = _required(created_by, "creator")
    stored = _validated(rules, rule_type, params)
    if host_id is not None and await db.get(Host, host_id) is None:
        raise RuleError(f"no host {host_id}")
    now = clock.now()
    rule = HealthRule(
        type=rule_type,
        name=(name or "").strip()[:NAME_LENGTH] or _default_name(rule_type, stored),
        params=stored,
        action=action,
        host_id=host_id,
        reason=reason,
        created_by=created_by,
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    db.add(rule)
    await db.flush()
    logger.info("rule %s (%s) added by %s: %s", rule.id, rule_type, created_by, reason)
    return rule


async def tune_rule(
    db: AsyncSession,
    clock: Clock,
    rule_id: int,
    *,
    params: dict[str, Any],
    reason: str,
    by: str,
    rules: RuleRegistry = registry,
) -> HealthRule:
    """Replace a rule's params; the new reason replaces the old, since it explains them."""
    reason = _required(reason, "reason")
    by = _required(by, "author")
    rule = await find_rule(db, rule_id)
    rule.params = _validated(rules, rule.type, params)
    rule.reason = reason
    rule.updated_at = clock.now()
    await db.flush()
    logger.info("rule %s tuned by %s: %s", rule.id, by, reason)
    return rule


async def set_enabled(
    db: AsyncSession, clock: Clock, rule_id: int, *, enabled: bool, by: str
) -> HealthRule:
    """A disabled rule is skipped by every evaluation until it is enabled again."""
    by = _required(by, "author")
    rule = await find_rule(db, rule_id)
    rule.enabled = enabled
    rule.updated_at = clock.now()
    await db.flush()
    logger.info("rule %s %s by %s", rule.id, "enabled" if enabled else "disabled", by)
    return rule


async def list_rules(db: AsyncSession) -> list[RuleView]:
    rules: Sequence[HealthRule] = (
        await db.scalars(select(HealthRule).order_by(HealthRule.id))
    ).all()
    views = []
    for rule in rules:
        latest = await db.scalar(
            select(Incident)
            .where(Incident.rule_id == rule.id)
            .order_by(Incident.opened_at.desc(), Incident.id.desc())
            .limit(1)
        )
        views.append(RuleView(rule, latest))
    return views
