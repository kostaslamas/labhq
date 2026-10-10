"""Save and load the policy table in `program_state`."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.models import ProgramState
from labhq.modelpolicy.policy import ModelPolicy, PolicyError, build, default_policy

KEY = "model_policy"


async def load_policy(db: AsyncSession) -> ModelPolicy:
    row = await db.get(ProgramState, KEY, populate_existing=True)
    if row is None:
        return default_policy()
    try:
        stored = json.loads(row.value)
    except json.JSONDecodeError:
        return default_policy()
    return build(stored) if isinstance(stored, dict) else default_policy()


async def save_policy(db: AsyncSession, clock: Clock, rows: dict[str, object]) -> ModelPolicy:
    """Validate `rows` over the stored table and keep the result; refuse unknown IDs."""
    current = await load_policy(db)
    merged: dict[str, object] = {key: row.model_dump() for key, row in current.rows.items()}
    merged.update(rows)
    policy = build(merged)
    value = json.dumps({key: row.model_dump() for key, row in policy.rows.items()})
    state = await db.get(ProgramState, KEY)
    if state is None:
        db.add(ProgramState(key=KEY, value=value, updated_at=clock.now()))
    else:
        state.value = value
        state.updated_at = clock.now()
    await db.commit()
    return policy


__all__ = ["PolicyError", "load_policy", "save_policy"]
