"""What a decision room is expected to cost: a range from recorded cost events (issue #202).

One turn is priced by the role that speaks it, from what past turns of that role cost: the
median for the low end and the 90th percentile for the high end. Each turn re-sends the
thread, so turn `k` costs more than turn 1. The growth is measured from the same history
(the same agent's later turns against its first) and assumed linear from settings when there
is too little of it. A role with too few recorded turns falls back to a constant from
settings, and the forecast says so: the UI must not present a guess as a measurement.

All amounts are integer micro-USD (ADR 0002); nothing here uses a float.
"""

from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from statistics import median_low

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.models import Agent, CostEvent, Meeting, MeetingParticipant, Run
from labhq.db.models import MeetingTranscriptEntry as Entry
from labhq.hierarchy import CEO
from labhq.meetings.settings import MeetingSettings

# Past meetings and CEO chat runs read for the history; older ones say little about today.
HISTORY_MEETINGS = 30
HISTORY_CHAT_RUNS = 30
PERMILLE = 1000


class Source(StrEnum):
    HISTORY = "history"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class Turn:
    """One recorded agent turn: who spoke, how far into its meeting, what it cost."""

    meeting_id: int | None
    agent_id: int
    role: str
    position: int
    cost_micros: int


@dataclass(frozen=True)
class Forecast:
    low_micros: int
    high_micros: int
    source: Source
    growth_permille: int
    # How each role's turn was priced, so the UI can say which part is a guess.
    role_sources: Mapping[str, Source]


def percentile(values: Collection[int], percent: int) -> int:
    """Nearest-rank percentile of a non-empty collection."""
    ordered = sorted(values)
    rank = (percent * len(ordered) + 99) // 100
    return ordered[max(rank, 1) - 1]


def growth_permille(turns: Collection[Turn], settings: MeetingSettings) -> int:
    """Extra cost per turn of thread, as a thousandth of the agent's first turn.

    Each agent's later turns in a meeting are compared with its own first turn there, so a
    role that simply costs more does not read as growth. Fewer slopes than
    `forecast_min_samples` give the assumed linear figure from settings.
    """
    by_agent: dict[tuple[int | None, int], list[Turn]] = defaultdict(list)
    for turn in turns:
        by_agent[(turn.meeting_id, turn.agent_id)].append(turn)
    slopes: list[int] = []
    for agent_turns in by_agent.values():
        agent_turns.sort(key=lambda turn: turn.position)
        first = agent_turns[0]
        slopes.extend(
            (turn.cost_micros - first.cost_micros) * PERMILLE // (first.cost_micros * span)
            for turn in agent_turns[1:]
            if (span := turn.position - first.position) > 0 and first.cost_micros > 0
        )
    if len(slopes) < settings.forecast_min_samples:
        return settings.growth_per_turn_permille
    return max(0, median_low(slopes))


def turn_factor(position: int, growth: int) -> int:
    """Turn `position` (1-based) costs this many thousandths of turn 1."""
    return PERMILLE + growth * (position - 1)


def forecast(
    history: Collection[Turn],
    roles: list[str],
    facilitator_role: str,
    settings: MeetingSettings,
) -> Forecast:
    """The range for a room whose seats speak in `roles` order, plus its minutes.

    The cap counts agent turns, which cycle through the seats; the minutes are one more run
    by the facilitator, at the end of the thread.
    """
    growth = growth_permille(history, settings)
    base: dict[str, tuple[int, int]] = {}
    sources: dict[str, Source] = {}
    for role in set(roles) | {facilitator_role}:
        samples = [
            turn.cost_micros * PERMILLE // turn_factor(turn.position, growth)
            for turn in history
            if turn.role == role
        ]
        if len(samples) >= settings.forecast_min_samples:
            base[role] = (percentile(samples, 50), percentile(samples, 90))
            sources[role] = Source.HISTORY
            continue
        low = settings.role_turn_estimate_micros.get(role, settings.decision_turn_estimate_micros)
        base[role] = (low, low * settings.fallback_high_percent // 100)
        sources[role] = Source.FALLBACK
    cap = settings.decision_turn_cap
    speakers = [roles[(position - 1) % len(roles)] for position in range(1, cap + 1)]
    speakers.append(facilitator_role)
    low_total = high_total = 0
    for position, role in enumerate(speakers, start=1):
        factor = turn_factor(position, growth)
        low_total += base[role][0] * factor // PERMILLE
        high_total += base[role][1] * factor // PERMILLE
    all_history = all(source is Source.HISTORY for source in sources.values())
    return Forecast(
        low_micros=low_total,
        high_micros=max(high_total, low_total),
        source=Source.HISTORY if all_history else Source.FALLBACK,
        growth_permille=growth,
        role_sources=sources,
    )


async def recorded_turns(db: AsyncSession) -> list[Turn]:
    """Agent turns of recent meetings and the CEO's chat runs, each with its recorded cost."""
    cost = (
        select(CostEvent.run_id, func.sum(CostEvent.cost_micros).label("cost"))
        .where(CostEvent.run_id.is_not(None), CostEvent.cost_micros > 0)
        .group_by(CostEvent.run_id)
        .subquery()
    )
    recent = select(Meeting.id).order_by(Meeting.id.desc()).limit(HISTORY_MEETINGS)
    rows = await db.execute(
        select(Entry.meeting_id, MeetingParticipant.agent_id, Agent.role, cost.c.cost)
        .join(MeetingParticipant, Entry.participant_id == MeetingParticipant.id)
        .join(Agent, MeetingParticipant.agent_id == Agent.id)
        .join(cost, cost.c.run_id == Entry.run_id)
        .where(Entry.meeting_id.in_(recent))
        .order_by(Entry.meeting_id, Entry.id)
    )
    turns: list[Turn] = []
    position = 0
    current: int | None = None
    for meeting_id, agent_id, role, spent in rows:
        position = position + 1 if meeting_id == current else 1
        current = meeting_id
        turns.append(Turn(meeting_id, agent_id, role, position, int(spent)))
    in_meetings = select(Entry.run_id).where(Entry.run_id.is_not(None))
    chat = await db.execute(
        select(Run.agent_id, cost.c.cost)
        .join(Agent, Run.agent_id == Agent.id)
        .join(cost, cost.c.run_id == Run.id)
        .where(Agent.role == CEO, Run.task_id.is_(None), Run.id.not_in(in_meetings))
        .order_by(Run.id.desc())
        .limit(HISTORY_CHAT_RUNS)
    )
    turns.extend(Turn(None, agent_id, CEO, 1, int(spent)) for agent_id, spent in chat)
    return turns


async def room_forecast(
    db: AsyncSession, agent_ids: list[int], facilitator_id: int, settings: MeetingSettings
) -> Forecast:
    """The forecast for a room of these agents, in seat order."""
    roles = {
        agent_id: role
        for agent_id, role in await db.execute(
            select(Agent.id, Agent.role).where(Agent.id.in_(agent_ids))
        )
    }
    return forecast(
        await recorded_turns(db),
        [roles[agent_id] for agent_id in agent_ids],
        roles[facilitator_id],
        settings,
    )
