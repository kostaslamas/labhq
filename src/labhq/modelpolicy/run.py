"""Resolve the model of one run: the policy table, the agent, the plan check."""

import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.modelpolicy.access import unusable_models
from labhq.modelpolicy.kinds import takes_model
from labhq.modelpolicy.resolve import Resolution, resolve
from labhq.modelpolicy.store import load_policy

log = logging.getLogger(__name__)


async def resolve_for_run(
    db: AsyncSession,
    clock: Clock,
    *,
    kind: str,
    role: str,
    config: Mapping[str, Any],
    request_model: str | None,
    task_kind: str | None,
) -> Resolution | None:
    """The run's model and effort, or None for a kind that takes no model."""
    if not takes_model(kind):
        log.info("agent kind %s takes no model; the policy row for %s is ignored", kind, role)
        return None
    agent_model = config.get("model")
    resolution = resolve(
        await load_policy(db),
        request_model=request_model,
        agent_model=agent_model if isinstance(agent_model, str) else None,
        task_kind=task_kind,
        role=role,
        unusable=await unusable_models(db, kind, clock),
    )
    log.info(
        "run model %s effort %s from %s (skipped %d)",
        resolution.model,
        resolution.effort,
        resolution.source,
        len(resolution.skipped),
    )
    return resolution
