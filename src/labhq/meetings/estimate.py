"""What a live room is expected to cost, shown to the owner before they approve its start.

The room is bounded by its turn cap, so the ceiling is the cap's turns plus the minutes at
the average cost of a recent run of the people in it (integer micro-USD, ADR 0002).
"""

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.models import CostEvent
from labhq.meetings.settings import MeetingSettings

SAMPLE = 20


async def room_estimate_micros(
    db: AsyncSession, agent_ids: Collection[int], settings: MeetingSettings
) -> int:
    recent = list(
        await db.scalars(
            select(CostEvent.cost_micros)
            .where(CostEvent.agent_id.in_(agent_ids), CostEvent.cost_micros > 0)
            .order_by(CostEvent.id.desc())
            .limit(SAMPLE)
        )
    )
    per_run = sum(recent) // len(recent) if recent else settings.decision_turn_estimate_micros
    return per_run * (settings.decision_turn_cap + 1)
