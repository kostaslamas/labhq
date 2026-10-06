import pytest

from labhq.autonomy import AutonomySettings
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent
from tests.scheduler.conftest import World, sessions, world

__all__ = ["World", "ceo_id", "sessions", "world"]

HEARTBEAT = 3600
SETTINGS = AutonomySettings(ceo_heartbeat_seconds=HEARTBEAT)


@pytest.fixture
async def ceo_id(world: World) -> int:
    """An active global CEO: no project, role `ceo`."""
    now = world.clock.now()
    async with world.sessions() as db:
        ceo = Agent(
            project_id=None,
            role="ceo",
            title="CEO",
            adapter="fake",
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add(ceo)
        await db.commit()
        return ceo.id
