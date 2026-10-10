"""The cost range of a room: recorded turns by role, growth, and the labelled fallback."""

from labhq.db.models import CostEvent, Run
from labhq.meetings import MeetingSettings
from labhq.meetings.forecast import (
    Source,
    Turn,
    forecast,
    growth_permille,
    percentile,
    recorded_turns,
    room_forecast,
)
from tests.meetings.conftest import World

FLAT = MeetingSettings(decision_turn_cap=4, growth_per_turn_permille=0, forecast_min_samples=5)


def _turns(role: str, costs: list[int], agent_id: int = 1) -> list[Turn]:
    return [Turn(None, agent_id, role, 1, cost) for cost in costs]


def test_percentiles_are_nearest_rank() -> None:
    values = [50, 10, 40, 20, 30, 60, 70, 80, 90, 100]
    assert percentile(values, 50) == 50
    assert percentile(values, 90) == 90
    assert percentile([7], 90) == 7


def test_with_no_history_the_range_is_the_constant_and_says_so() -> None:
    result = forecast([], ["ceo", "manager"], "ceo", FLAT)

    # Four turns and the minutes, at the constant; the high end is double it.
    assert (result.low_micros, result.high_micros) == (5 * 200_000, 5 * 400_000)
    assert result.source is Source.FALLBACK
    assert dict(result.role_sources) == {"ceo": Source.FALLBACK, "manager": Source.FALLBACK}


def test_a_constant_per_role_overrides_the_default() -> None:
    settings = FLAT.model_copy(update={"role_turn_estimate_micros": {"manager": 1_000_000}})

    result = forecast([], ["ceo", "manager"], "ceo", settings)

    # ceo, manager, ceo, manager, then the ceo's minutes.
    assert result.low_micros == 3 * 200_000 + 2 * 1_000_000


def test_the_range_is_the_median_to_the_90th_percentile_by_role() -> None:
    history = [
        *_turns("ceo", [100_000] * 8 + [300_000, 300_000]),
        *_turns("manager", [200_000] * 10),
    ]

    result = forecast(history, ["ceo", "manager"], "ceo", FLAT)

    assert result.source is Source.HISTORY
    assert result.low_micros == 3 * 100_000 + 2 * 200_000
    assert result.high_micros == 3 * 100_000 + 2 * 200_000 + 3 * 200_000  # p90 of the ceo: 300k


def test_a_role_with_too_few_turns_makes_the_whole_range_a_fallback() -> None:
    history = [*_turns("ceo", [100_000] * 10), *_turns("manager", [200_000] * 2)]

    result = forecast(history, ["ceo", "manager"], "ceo", FLAT)

    assert result.source is Source.FALLBACK
    assert dict(result.role_sources) == {"ceo": Source.HISTORY, "manager": Source.FALLBACK}
    # The ceo's turns use history, the manager's the constant.
    assert result.low_micros == 3 * 100_000 + 2 * 200_000


def _grown(per_position_permille: int, meetings: int) -> list[Turn]:
    """One agent whose turn at position `p` costs 100,000 grown linearly from turn 1."""
    return [
        Turn(
            meeting,
            1,
            "ceo",
            position,
            100_000 * (1000 + per_position_permille * (position - 1)) // 1000,
        )
        for meeting in range(meetings)
        for position in (1, 3, 5)
    ]


def test_growth_is_measured_from_later_turns_against_the_agents_first() -> None:
    assert growth_permille(_grown(50, meetings=3), FLAT) == 50


def test_too_few_measurements_assume_the_linear_growth_from_settings() -> None:
    settings = FLAT.model_copy(update={"growth_per_turn_permille": 70})
    assert growth_permille(_grown(50, meetings=1), settings) == 70


def test_recorded_growth_raises_the_range_over_the_flat_one() -> None:
    history = _grown(50, meetings=3) + _turns("manager", [100_000] * 5)
    grown = forecast(history, ["ceo", "manager"], "ceo", FLAT.model_copy(update={}))
    flat = forecast(
        [Turn(t.meeting_id, t.agent_id, t.role, 1, t.cost_micros) for t in history],
        ["ceo", "manager"],
        "ceo",
        FLAT,
    )

    assert grown.growth_permille == 50
    # Turn k costs 1 + 0.05 (k - 1) of turn 1 over five runs: 1 + 1.05 + 1.1 + 1.15 + 1.2.
    assert grown.low_micros == 100_000 * 5_500 // 1000
    assert grown.low_micros > flat.low_micros


async def test_history_comes_from_recorded_cost_events_of_past_rooms(world: World) -> None:
    world.stage.minutes.extend(world.minutes_json() for _ in range(2))
    for _ in range(2):
        meeting_id = await world.approved_meeting("decision")
        await world.service.start(meeting_id)
        await world.room.close(meeting_id)
    settings = world.room._settings.model_copy(
        update={"decision_turn_cap": 2, "growth_per_turn_permille": 0, "forecast_min_samples": 2}
    )

    async with world.sessions() as db:
        turns = await recorded_turns(db)
        result = await room_forecast(db, [world.ceo_id, world.manager_id], world.ceo_id, settings)

    assert sorted((t.role, t.position) for t in turns) == [
        ("ceo", 1),
        ("ceo", 1),
        ("manager", 2),
        ("manager", 2),
    ]
    assert result.source is Source.HISTORY
    # Two turns and the minutes, each recorded at 12,500.
    assert (result.low_micros, result.high_micros) == (3 * 12_500, 3 * 12_500)


async def test_ceo_chat_runs_count_as_ceo_turns(world: World) -> None:
    async with world.sessions() as db:
        run = Run(
            agent_id=world.ceo_id,
            adapter="fake",
            created_at=world.clock.now(),
        )
        db.add(run)
        await db.flush()
        db.add(
            CostEvent(
                run_id=run.id,
                agent_id=world.ceo_id,
                project_id=None,
                cost_micros=40_000,
                created_at=world.clock.now(),
            )
        )
        await db.commit()
        turns = await recorded_turns(db)

    assert [(t.role, t.meeting_id, t.cost_micros) for t in turns] == [("ceo", None, 40_000)]
