"""Read and set whether the organisation acts on its own."""

from fastapi import APIRouter
from pydantic import BaseModel

from labhq.api.deps import ContextDep, SessionDep
from labhq.autonomy import Autonomy, get_autonomy, get_autonomy_settings, set_autonomy

# The router registry requires the owner for every route registered here.
router = APIRouter(tags=["autonomy"])


class AutonomyState(BaseModel):
    autonomy: Autonomy


@router.get("/autonomy")
async def autonomy_get(db: SessionDep) -> AutonomyState:
    return AutonomyState(autonomy=await get_autonomy(db, get_autonomy_settings()))


@router.put("/autonomy")
async def autonomy_put(body: AutonomyState, context: ContextDep) -> AutonomyState:
    """`paused` stops timers, heartbeats and automatic next turns; owner messages still run."""
    async with context.sessions() as db:
        return AutonomyState(autonomy=await set_autonomy(db, context.clock, body.autonomy))
