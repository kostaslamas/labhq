"""A limit notice on the screen holds the agent kind until its reset; a fallback takes over."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from labhq.db.enums import RunStatus
from labhq.db.models import Run, RunEvent, UsageReading
from labhq.scheduler import Verdict
from labhq.scheduler.dispatch import TAKEOVER_NOTE
from labhq.usage.collect import UsageCollector
from labhq.usage.extractors import ExtractorRegistry
from tests.scheduler.conftest import World
from tests.scheduler.helpers import on_task
from tests.usage.extracting import ANSWERS, FakeExtractor, screen
from tests.usage.plan_world import PLAN, notifications, on_kind

NOTICE = "claude_limit_notice.txt"
RESETS_AT = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)


async def finished_run(world: World, kind: str, events: dict[str, dict[str, object]]) -> int:
    """A finished tmux run that left `events` behind, as the adapter does."""
    async with world.sessions() as db:
        now = world.clock.now()
        run = Run(
            agent_id=world.agent_id,
            task_id=world.task_id,
            adapter="tmux",
            status=RunStatus.SUCCEEDED,
            created_at=now,
        )
        db.add(run)
        await db.flush()
        rows = {"agent": {"kind": kind}, **events}
        for seq, (event_kind, payload) in enumerate(rows.items(), start=1):
            db.add(
                RunEvent(run_id=run.id, seq=seq, kind=event_kind, payload=payload, created_at=now)
            )
        await db.commit()
        return run.id


def collector(world: World, extractor: FakeExtractor) -> UsageCollector:
    registry = ExtractorRegistry()
    registry.register("model", extractor)
    return UsageCollector(world.sessions, clock=world.clock, extractors=registry, settings=PLAN)


async def readings(world: World) -> list[UsageReading]:
    async with world.sessions() as db:
        return list(await db.scalars(select(UsageReading).order_by(UsageReading.id)))


async def test_a_limit_notice_pauses_the_kind_notifies_and_resumes_after_the_reset(
    world: World,
) -> None:
    scheduler = await on_kind(world, {"agent": "fake-a"})
    extractor = FakeExtractor(ANSWERS[NOTICE])
    run_id = await finished_run(world, "fake-a", {"screen_final": {"text": screen(NOTICE)}})

    report = await collector(world, extractor).collect([run_id])

    assert report.limit_notices == [run_id]
    assert extractor.seen == [(screen(NOTICE), "fake-a")]
    (notice,) = await readings(world)
    assert (notice.source, notice.window, notice.value, notice.resets_at) == (
        "limit_notice",
        "limit_notice",
        100.0,
        RESETS_AT,
    )
    (notification,) = await notifications(world)
    assert "No new fake-a runs start until 2026-10-02 15:00 UTC" in notification.body

    await scheduler.enqueue(on_task(world, "after-limit"))
    paused = await scheduler.tick()
    assert paused.started == []
    assert list(paused.waiting.values()) == [Verdict.PLAN_PAUSED]

    world.clock.set(RESETS_AT + timedelta(seconds=1))
    resumed = await scheduler.tick()
    await scheduler.settle()
    assert len(resumed.started) == 1


async def test_a_notice_without_a_reset_time_holds_for_the_configured_time(world: World) -> None:
    await on_kind(world, {"agent": "fake-a"})
    extractor = FakeExtractor({"readings": [], "limit_notice": True})
    run_id = await finished_run(world, "fake-a", {"screen_final": {"text": screen(NOTICE)}})

    await collector(world, extractor).collect([run_id])

    (notice,) = await readings(world)
    assert notice.resets_at == world.clock.now() + timedelta(seconds=PLAN.plan_limit_hold_seconds)


async def test_a_failed_extraction_is_a_failed_reading_never_zero(world: World) -> None:
    await on_kind(world, {"agent": "fake-a"})
    invented = {"readings": [{"unit": "percent", "value": 33, "window": "5h"}]}
    run_id = await finished_run(
        world, "fake-a", {"usage_screen": {"text": screen("codex_status.txt")}}
    )

    report = await collector(world, FakeExtractor(invented)).collect([run_id])

    (row,) = await readings(world)
    assert (row.value, row.unit, row.source) == (None, None, "screen")
    assert row.error is not None and "33" in row.error
    assert report.failures and report.limit_notices == []


async def test_the_statusline_is_read_without_the_extractor(world: World) -> None:
    await on_kind(world, {"agent": "claude-code"})
    extractor = FakeExtractor("{}")
    document = {
        "rate_limits": {"five_hour": {"used_percentage": 12, "resets_at": 1791043200}},
        "cost": {"total_cost_usd": 0.5},
    }
    run_id = await finished_run(world, "claude-code", {"statusline": document})

    await collector(world, extractor).collect([run_id])

    assert extractor.seen == []
    (row,) = await readings(world)
    assert (row.unit, row.window, row.value, row.source) == (
        "percent",
        "five_hour",
        12.0,
        "statusline",
    )


async def test_runs_without_tmux_captures_are_skipped(world: World) -> None:
    extractor = FakeExtractor(ANSWERS[NOTICE])
    async with world.sessions() as db:
        run = Run(agent_id=world.agent_id, adapter="fake", created_at=world.clock.now())
        db.add(run)
        await db.commit()

    report = await collector(world, extractor).collect([run.id])

    assert (report.readings, report.failures, extractor.seen) == (0, [], [])


async def test_with_a_fallback_the_paused_task_continues_on_the_other_kind(world: World) -> None:
    scheduler = await on_kind(world, {"agent": "fake-a", "fallback_agent": "fake-b"})
    run_id = await finished_run(world, "fake-a", {"screen_final": {"text": screen(NOTICE)}})
    await collector(world, FakeExtractor(ANSWERS[NOTICE])).collect([run_id])

    await scheduler.enqueue(on_task(world, "after-limit"))
    report = await scheduler.tick()
    await scheduler.settle()

    assert len(report.started) == 1
    request = world.fake.requests[-1]
    assert request.config["agent"] == "fake-b"
    assert request.config["fallback_agent"] == "fake-b"
    assert TAKEOVER_NOTE in request.prompt


async def test_a_fallback_past_its_own_share_does_not_start_either(world: World) -> None:
    scheduler = await on_kind(world, {"agent": "fake-a", "fallback_agent": "fake-b"})
    for kind in ("fake-a", "fake-b"):
        run_id = await finished_run(world, kind, {"screen_final": {"text": screen(NOTICE)}})
        await collector(world, FakeExtractor(ANSWERS[NOTICE])).collect([run_id])

    await scheduler.enqueue(on_task(world, "after-limit"))

    assert (await scheduler.tick()).started == []
