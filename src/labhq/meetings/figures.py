"""The cost figures of one decision room, read the same way by the widget and the Call Center.

Without `ANTHROPIC_API_KEY` the agents run on the owner's subscription, which has no USD bill
(ADR 0001): the same numbers then read as an equivalent cost, next to the share of the plan
window they used, where `labhq.usage` has a reading. Only whether the variable is set is read,
never its value.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters.claude_env import API_KEY_VARIABLE
from labhq.clock import Clock
from labhq.db.models import Agent, Meeting, MeetingParticipant
from labhq.db.models import MeetingTranscriptEntry as Entry
from labhq.meetings.cost import meeting_cost_micros
from labhq.meetings.settings import MeetingSettings
from labhq.usage.plan import agent_kind, check_kind


@dataclass(frozen=True)
class RoomFigures:
    meeting_id: int
    spent_micros: int
    low_micros: int | None
    high_micros: int | None
    cap_micros: int | None
    # "history" or "fallback": whether the range is measured or a constant from settings.
    source: str | None
    turns: int
    turn_cap: int
    equivalent_cost: bool
    # The busiest plan window of the room's agent kinds; None when no reading is recorded.
    plan_used_percent: float | None


def bills_usd(environ: Mapping[str, str] = os.environ) -> bool:
    return bool(environ.get(API_KEY_VARIABLE))


async def room_figures(
    db: AsyncSession,
    clock: Clock,
    meeting: Meeting,
    settings: MeetingSettings,
    environ: Mapping[str, str] = os.environ,
) -> RoomFigures:
    turns = await db.scalar(
        select(func.count(Entry.id)).where(
            Entry.meeting_id == meeting.id, Entry.run_id.is_not(None)
        )
    )
    equivalent = not bills_usd(environ)
    return RoomFigures(
        meeting_id=meeting.id,
        spent_micros=await meeting_cost_micros(db, meeting.id),
        low_micros=meeting.estimate_micros,
        high_micros=meeting.estimate_high_micros,
        cap_micros=meeting.cost_cap_micros,
        source=meeting.estimate_source,
        turns=turns or 0,
        turn_cap=settings.decision_turn_cap,
        equivalent_cost=equivalent,
        plan_used_percent=await _plan_share(db, clock, meeting.id) if equivalent else None,
    )


async def _plan_share(db: AsyncSession, clock: Clock, meeting_id: int) -> float | None:
    agents = await db.scalars(
        select(Agent)
        .join(MeetingParticipant, MeetingParticipant.agent_id == Agent.id)
        .where(MeetingParticipant.meeting_id == meeting_id)
    )
    kinds = {agent_kind(agent.adapter, agent.config) for agent in agents}
    used = [
        window.used_percent
        for kind in sorted(kinds)
        for window in (await check_kind(db, kind, clock)).windows
    ]
    return max(used) if used else None
