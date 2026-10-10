"""Models the logged-in account cannot use right now, read from `labhq.usage`.

Claude plans cap some model families on their own window (`seven_day_opus`). A window of
that shape that stops new runs makes every model of the family unusable until it resets.
A window without a family, such as `five_hour`, holds the whole agent kind and is the
scheduler's business (ADR 0003), so it does not skip a policy row.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.budgets import Decision
from labhq.clock import Clock
from labhq.modelpolicy.catalog import CATALOG
from labhq.usage.plan import check_kind


async def unusable_models(db: AsyncSession, kind: str, clock: Clock) -> dict[str, str]:
    """Model ID -> why it cannot be used, for the agent kind."""
    check = await check_kind(db, kind, clock)
    blocked: dict[str, str] = {}
    for window in check.windows:
        if window.decision is not Decision.STOP:
            continue
        for model in CATALOG:
            if window.window.endswith(f"_{model.family}") or window.window == model.family:
                blocked[model.id] = f"{window.window} is at {window.used_percent:g}% of the plan"
    return blocked
