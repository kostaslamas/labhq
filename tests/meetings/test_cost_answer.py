"""`room_cost` answers from the room's recorded figures, aloud-safe, with no model."""

from labhq.callcenter.answers.room_cost import NO_ROOM, room_cost
from tests.meetings.conftest import World
from tests.meetings.test_room_cost import RUN_COST, _room


async def test_no_room_says_so(world: World) -> None:
    async with world.sessions() as db:
        assert await room_cost(db, world.clock, {}) == NO_ROOM


async def test_a_room_waiting_for_approval_gives_the_range_and_the_cap(world: World) -> None:
    await _room(world, decision_cost_cap_micros=2_000_000)
    async with world.sessions() as db:
        answer = await room_cost(db, world.clock, {})
    # A request is pending, so nothing ran: the figures are the labelled guess.
    assert "has not started" in answer
    assert "equivalent cost is expected between 4 dollars and 16 cents and 8 dollars" in answer
    assert "a rough guess" in answer
    assert "hard cap is 2 dollars" in answer


async def test_a_running_room_gives_the_total_and_a_billed_room_says_cost(world: World) -> None:
    meeting_id = await _room(world)
    await world.service.start(meeting_id)
    async with world.sessions() as db:
        subscription = await room_cost(db, world.clock, {})
        billed = await room_cost(db, world.clock, {"ANTHROPIC_API_KEY": "x"})
    assert f"Its equivalent cost so far is {RUN_COST * 2 // 10_000} cents" not in subscription
    assert "equivalent cost so far is 3 cents over 2 of 12 turns" in subscription
    assert "Its cost so far is 3 cents over 2 of 12 turns" in billed
    assert "equivalent" not in billed
