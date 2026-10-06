"""The program's self-driving steps: the CEO heartbeat and the meeting cadence."""

from sqlalchemy import select

from labhq.autonomy.heartbeat import heartbeat_pass
from labhq.autonomy.settings import Autonomy, get_autonomy_settings
from labhq.autonomy.state import get_autonomy
from labhq.cli.context import Context
from labhq.cli.engine import Engine
from labhq.cli.meetings import meeting_service
from labhq.db.models import Project


async def heartbeat_step(context: Context, engine: Engine) -> int:
    return len(await heartbeat_pass(context.sessions, context.clock, engine.scheduler.enqueue))


async def meetings_step(context: Context) -> int:
    """Request each project's due meetings, then run the ones the owner has decided."""
    async with context.sessions() as db:
        paused = await get_autonomy(db, get_autonomy_settings()) is Autonomy.PAUSED
        projects = list(await db.scalars(select(Project.id).order_by(Project.id)))
    service = meeting_service(context)
    requested = 0
    if not paused:
        for project_id in projects:
            requested += len(await service.request_due(project_id))
    # An approved meeting still runs while paused: the owner decided it, not the cadence.
    return requested + len(await service.start_decided())
