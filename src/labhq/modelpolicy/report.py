"""Cost by model, in integer micro-USD (ADR 0002), and what the policy saves.

`reference_micros` is what the same tokens would cost at the worker model's list price, so
`saved_micros` shows the policy's effect; it is an estimate from list prices and counts
input and output tokens only.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.models import CostEvent
from labhq.modelpolicy.catalog import estimate_micros
from labhq.modelpolicy.policy import SONNET

UNKNOWN = "unknown"


@dataclass(frozen=True)
class ModelCost:
    model: str
    runs: int
    cost_micros: int
    input_tokens: int
    output_tokens: int
    reference_micros: int | None

    @property
    def saved_micros(self) -> int | None:
        if self.reference_micros is None:
            return None
        return self.reference_micros - self.cost_micros


def _reference(model: str, tokens_in: int, tokens_out: int) -> int | None:
    # An unknown model has no list price to compare against.
    if estimate_micros(model, 0, 0) is None:
        return None
    return estimate_micros(SONNET, tokens_in, tokens_out)


async def cost_by_model(
    db: AsyncSession, since: datetime | None = None, until: datetime | None = None
) -> list[ModelCost]:
    model = func.coalesce(CostEvent.model, UNKNOWN)
    query = select(
        model,
        func.count(CostEvent.id),
        func.coalesce(func.sum(CostEvent.cost_micros), 0),
        func.coalesce(func.sum(CostEvent.input_tokens), 0),
        func.coalesce(func.sum(CostEvent.output_tokens), 0),
    ).group_by(model)
    if since is not None:
        query = query.where(CostEvent.created_at >= since)
    if until is not None:
        query = query.where(CostEvent.created_at < until)
    rows = (await db.execute(query.order_by(func.sum(CostEvent.cost_micros).desc()))).all()
    return [
        ModelCost(
            name,
            int(runs),
            int(cost),
            int(tokens_in),
            int(tokens_out),
            _reference(name, int(tokens_in), int(tokens_out)),
        )
        for name, runs, cost, tokens_in, tokens_out in rows
    ]
