"""Meetings on a cadence: off by default, a setting per kind (plan §13, question 3)."""

from labhq.db.enums import MeetingStatus
from labhq.meetings import MeetingService, MeetingSettings
from tests.meetings.conftest import World


def _service(world: World, settings: MeetingSettings) -> MeetingService:
    return MeetingService(
        world.sessions,
        clock=world.clock,
        approvals=world.approvals,
        runner=world.runner,
        kinds=world.kinds,
        settings=settings,
    )


def test_no_cadence_is_set_by_default() -> None:
    assert MeetingSettings().cadence_seconds == {}


async def test_without_a_cadence_nothing_is_requested(world: World) -> None:
    assert await world.service.request_due(world.project_id) == []


async def test_a_cadence_requests_a_meeting_once_per_interval(world: World) -> None:
    service = _service(world, MeetingSettings(cadence_seconds={"standup": 3600}))

    first = await service.request_due(world.project_id)
    again = await service.request_due(world.project_id)
    world.clock.advance(3600)
    later = await service.request_due(world.project_id)

    assert [(m.kind, m.status) for m in first] == [("standup", MeetingStatus.REQUESTED)]
    assert again == []
    assert len(later) == 1
