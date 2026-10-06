"""The CEO's actions, recorded with the CEO as the actor.

An action is a `run_events` row of kind `ceo_action` on the CEO's current run, so the owner
reads what the CEO did in the same place as everything else a run did. The agent comes from
the tool context, never from an argument.
"""

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.agenttools import ToolContext
from labhq.db.models import Run, RunEvent

logger = logging.getLogger(__name__)

CEO_ACTION = "ceo_action"


def actor(agent_id: int) -> str:
    """How a string records that the CEO did something: `decided_by`, `created_by`."""
    return f"agent:{agent_id}"


async def _run_of(db: AsyncSession, context: ToolContext) -> int | None:
    if context.run_id is not None:
        return context.run_id
    # A pane that outlives its first run has none bound: the CEO's latest run stands in.
    return await db.scalar(
        select(Run.id).where(Run.agent_id == context.agent_id).order_by(Run.id.desc()).limit(1)
    )


async def record_action(context: ToolContext, tool: str, details: dict[str, Any]) -> None:
    payload = {"actor": actor(context.agent_id), "tool": tool, **details}
    async with context.sessions() as db:
        run_id = await _run_of(db, context)
        if run_id is None:
            logger.info("ceo action without a run: %s", payload)
            return
        seq = await db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id))
        db.add(
            RunEvent(
                run_id=run_id,
                seq=(seq or 0) + 1,
                kind=CEO_ACTION,
                payload=payload,
                created_at=context.clock.now(),
            )
        )
        await db.commit()
