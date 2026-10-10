"""The `change_models` approval: the owner approves a table change, the engine applies it.

Nothing applies a change on request. The executor runs once a passkey has approved it.
"""

import asyncio
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from labhq.clock import Clock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.modelpolicy.policy import PolicyRow, build
from labhq.modelpolicy.store import save_policy
from labhq.settings import Settings

CHANGE_ACTION = "change_models"


class ChangePayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rows: dict[str, PolicyRow]

    def validated(self) -> None:
        build({key: row.model_dump() for key, row in self.rows.items()})


def validate_change(payload: Mapping[str, Any]) -> object:
    parsed = ChangePayload.model_validate(payload)
    parsed.validated()
    return parsed


async def _apply(rows: dict[str, object], clock: Clock) -> None:
    # Read per call, not from the cached settings: the executor runs in its own thread.
    engine = create_engine(Settings().resolved_database_url)
    try:
        async with session_factory(engine)() as db:
            await save_policy(db, clock, rows)
    finally:
        await engine.dispose()


def apply_change(payload: Mapping[str, Any]) -> dict[str, Any]:
    parsed = ChangePayload.model_validate(payload)
    rows = {key: row.model_dump() for key, row in parsed.rows.items()}
    # The executor runs in a worker thread, so it owns a loop and a connection of its own.
    asyncio.run(_apply(dict(rows), SystemClock()))
    return {"applied": sorted(rows)}
