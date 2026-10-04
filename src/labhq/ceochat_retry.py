"""Retry a direct CEO message on its backup after the primary hits a plan limit."""

import json
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters.kinds import UnknownAgentChoiceError, choice_named
from labhq.budgets import Decision
from labhq.clock import Clock
from labhq.db.enums import RunStatus, WakeupSource, WakeupStatus
from labhq.db.models import Agent, Run, RunEvent, WakeupRequest
from labhq.usage.plan import agent_kind, check_kind, fallback_kind
from labhq.usage.settings import UsageSettings


def _installed(kind: str) -> bool:
    try:
        choice = choice_named(kind)
    except UnknownAgentChoiceError:
        return True  # Custom adapters and test doubles own their availability.
    return choice.found() is not None


async def retry_limited_messages(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    run_ids: Sequence[int],
    settings: UsageSettings,
) -> list[int]:
    """Put a failed owner turn back in the queue once, if its backup can take over."""
    retried: list[int] = []
    async with sessions() as db:
        for run_id in run_ids:
            run = await db.get(Run, run_id)
            if run is None or run.status not in {RunStatus.FAILED, RunStatus.TIMED_OUT}:
                continue
            request = await db.scalar(
                select(WakeupRequest).where(
                    WakeupRequest.run_id == run_id,
                    WakeupRequest.source == WakeupSource.OWNER_MESSAGE,
                    WakeupRequest.status == WakeupStatus.DISPATCHED,
                )
            )
            if request is None:
                continue
            try:
                reason = json.loads(request.reason)
            except ValueError:
                continue
            if not isinstance(reason, dict) or reason.get("backup_retry"):
                continue
            agent = await db.get_one(Agent, run.agent_id)
            primary = agent_kind(agent.adapter, agent.config)
            backup = fallback_kind(agent.config)
            if backup is None or backup == primary or not _installed(backup):
                continue
            started_kind = await db.scalar(
                select(RunEvent.payload).where(RunEvent.run_id == run_id, RunEvent.kind == "agent")
            )
            if isinstance(started_kind, dict):
                if started_kind.get("kind") != primary:
                    continue
            elif run.adapter != agent.adapter:
                continue
            if (await check_kind(db, primary, clock, settings)).decision is not Decision.STOP:
                continue
            if (await check_kind(db, backup, clock, settings)).decision is Decision.STOP:
                continue
            reason["backup_retry"] = True
            request.reason = json.dumps(reason, ensure_ascii=False)
            request.status = WakeupStatus.PENDING
            request.run_id = None
            request.updated_at = clock.now()
            retried.append(request.id)
        await db.commit()
    return retried
