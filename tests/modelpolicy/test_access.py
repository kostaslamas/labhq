"""A model family whose own plan window stops new runs is unusable until it resets."""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.models import UsageReading
from labhq.modelpolicy.access import unusable_models
from tests.db.factories import project_agent_task


async def reading(db: AsyncSession, clock: FakeClock, window: str, percent: int) -> None:
    _, agent, _ = await project_agent_task(db, clock)
    db.add(
        UsageReading(
            agent_id=agent.id,
            agent_kind="claude",
            unit="percent",
            value=percent,
            window=window,
            resets_at=clock.now() + timedelta(hours=3),
            source="test",
            created_at=clock.now(),
        )
    )
    await db.commit()


async def test_a_capped_family_blocks_its_models_only(
    session: AsyncSession, clock: FakeClock
) -> None:
    await reading(session, clock, "seven_day_opus", 95)
    assert list(await unusable_models(session, "claude", clock)) == ["claude-opus-5-5"]


async def test_a_whole_plan_window_does_not_skip_a_row(
    session: AsyncSession, clock: FakeClock
) -> None:
    await reading(session, clock, "five_hour", 99)
    assert await unusable_models(session, "claude", clock) == {}
