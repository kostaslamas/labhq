"""The program's meeting step requests due meetings and starts the ones the owner decided."""

import pytest
from sqlalchemy import select

from labhq.approvals import ApprovalService
from labhq.autonomy import Autonomy, set_autonomy
from labhq.autonomy.loops import meetings_step
from labhq.cli.context import Context
from labhq.db.enums import AgentStatus, MeetingStatus
from labhq.db.models import Agent, Meeting
from labhq.meetings.settings import get_meeting_settings
from labhq.settings import Settings
from tests.autonomy.conftest import World


@pytest.fixture
def context(world: World, tmp_path) -> Context:
    settings = Settings(data_dir=tmp_path / "data")
    return Context(settings, world.sessions, world.clock)


@pytest.fixture(autouse=True)
def hourly_standup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_MEETINGS_CADENCE_SECONDS", '{"standup": 3600}')
    get_meeting_settings.cache_clear()
    yield
    get_meeting_settings.cache_clear()


async def _manager(world: World) -> None:
    async with world.sessions() as db:
        agent = await db.get_one(Agent, world.agent_id)
        agent.role = "manager"
        agent.status = AgentStatus.ACTIVE
        await db.commit()


async def _meetings(world: World) -> list[Meeting]:
    async with world.sessions() as db:
        return list(await db.scalars(select(Meeting).order_by(Meeting.id)))


async def test_a_due_meeting_is_requested_then_started_once_approved(
    world: World, context: Context
) -> None:
    await _manager(world)

    assert await meetings_step(context) == 1
    (meeting,) = await _meetings(world)
    assert meeting.status is MeetingStatus.REQUESTED
    assert meeting.approval_id is not None

    # Not due again while the cadence has not elapsed, and not started while undecided.
    assert await meetings_step(context) == 0

    await ApprovalService(world.sessions, clock=world.clock).approve(
        meeting.approval_id, decider="owner", confirmation="voice"
    )
    await meetings_step(context)

    (started,) = await _meetings(world)
    assert started.status is not MeetingStatus.REQUESTED


async def test_paused_autonomy_requests_no_meeting(world: World, context: Context) -> None:
    await _manager(world)
    async with world.sessions() as db:
        await set_autonomy(db, world.clock, Autonomy.PAUSED)

    assert await meetings_step(context) == 0
    assert await _meetings(world) == []
