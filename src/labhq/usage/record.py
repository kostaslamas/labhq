"""Store readings: USD as `cost_events` through `labhq.money`, the rest as `usage_readings`.

Neither function commits; the caller owns the transaction.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.models import CostEvent, UsageReading
from labhq.money import usd_to_micros
from labhq.usage.schema import Reading, UsageUnit


@dataclass(frozen=True)
class ReadingContext:
    """Who and what a reading is about."""

    agent_id: int
    agent_kind: str
    run_id: int | None
    project_id: int | None
    source: str
    now: datetime


def record_readings(
    db: AsyncSession, context: ReadingContext, readings: list[Reading]
) -> tuple[list[CostEvent], list[UsageReading]]:
    costs: list[CostEvent] = []
    others: list[UsageReading] = []
    for reading in readings:
        if reading.unit is UsageUnit.USD:
            costs.append(_cost_event(context, reading))
        else:
            others.append(_usage_reading(context, reading))
    db.add_all([*costs, *others])
    return costs, others


def record_failure(db: AsyncSession, context: ReadingContext, error: str) -> UsageReading:
    row = UsageReading(
        agent_id=context.agent_id,
        run_id=context.run_id,
        agent_kind=context.agent_kind,
        source=context.source,
        error=error,
        created_at=context.now,
    )
    db.add(row)
    return row


def _cost_event(context: ReadingContext, reading: Reading) -> CostEvent:
    return CostEvent(
        run_id=context.run_id,
        agent_id=context.agent_id,
        project_id=context.project_id,
        cost_micros=usd_to_micros(reading.value),
        created_at=context.now,
    )


def _usage_reading(context: ReadingContext, reading: Reading) -> UsageReading:
    # Percentages and token counts are measurements, not money; a float holds them.
    return UsageReading(
        agent_id=context.agent_id,
        run_id=context.run_id,
        agent_kind=context.agent_kind,
        source=context.source,
        unit=reading.unit.value,
        window=reading.window,
        value=float(reading.value),
        limit_value=float(reading.limit) if reading.limit is not None else None,
        resets_at=reading.resets_at,
        created_at=context.now,
    )
