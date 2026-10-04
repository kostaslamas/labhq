"""`/api/health/rules`: why each rule exists, and the light action of switching one off.

Everything goes through `labhq.health.manage`, so the UI, the CLI and an agent share one set of
checks. A rule only notifies or opens a ticket, so disabling one is a light owner action: a
signed-in session is enough, no passkey step-up.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.api.deps import ClockDep, OwnerDep, SessionDep
from labhq.api.errors import ApiError
from labhq.db.enums import HealthRuleAction, IncidentStatus
from labhq.db.models import Host
from labhq.health.manage import RuleError, RuleView, list_rules, set_enabled

router = APIRouter(prefix="/health/rules", tags=["rules"])

RULE_NOT_FOUND_CODE = "rule_not_found"


class HealthRuleLatest(BaseModel):
    """The rule's most recent incident, open or resolved: what it last observed."""

    incident_id: int
    status: IncidentStatus
    opened_at: datetime
    resolved_at: datetime | None
    details: dict[str, Any]


class HealthRuleItem(BaseModel):
    id: int
    name: str
    type: str
    params: dict[str, Any]
    action: HealthRuleAction
    # None: the rule applies to every host.
    host: str | None
    reason: str
    created_by: str
    enabled: bool
    created_at: datetime
    # Moves on tuning and on enabling or disabling, so for a disabled rule it is when it was
    # switched off.
    updated_at: datetime
    latest: HealthRuleLatest | None


class HealthRuleEnabledBody(BaseModel):
    enabled: bool


def present(view: RuleView, hosts: dict[int, str]) -> HealthRuleItem:
    rule, latest = view.rule, view.latest
    return HealthRuleItem(
        id=rule.id,
        name=rule.name,
        type=rule.type,
        params=rule.params,
        action=rule.action,
        host=hosts.get(rule.host_id) if rule.host_id is not None else None,
        reason=rule.reason,
        created_by=rule.created_by,
        enabled=rule.enabled,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        latest=None
        if latest is None
        else HealthRuleLatest(
            incident_id=latest.id,
            status=latest.status,
            opened_at=latest.opened_at,
            resolved_at=latest.resolved_at,
            details=latest.details,
        ),
    )


async def _host_names(db: AsyncSession) -> dict[int, str]:
    return {row.id: row.name for row in await db.execute(select(Host.id, Host.name))}


@router.get("")
async def rules_list(db: SessionDep) -> list[HealthRuleItem]:
    """Every rule with its reason, creator and latest result."""
    hosts = await _host_names(db)
    return [present(view, hosts) for view in await list_rules(db)]


@router.post("/{rule_id}/enabled")
async def rules_set_enabled(
    rule_id: int, body: HealthRuleEnabledBody, db: SessionDep, clock: ClockDep, owner: OwnerDep
) -> HealthRuleItem:
    """Enable or disable a rule, recorded with the signed-in owner as `by`."""
    try:
        await set_enabled(db, clock, rule_id, enabled=body.enabled, by=owner.subject)
    except RuleError as error:
        raise ApiError(404, RULE_NOT_FOUND_CODE, str(error)) from None
    await db.commit()
    hosts = await _host_names(db)
    return next(present(view, hosts) for view in await list_rules(db) if view.rule.id == rule_id)
