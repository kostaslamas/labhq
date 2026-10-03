import time

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers import brief, health, inbox
from labhq.clock import FakeClock
from tests.callcenter.answers.seed import seed_busy, seed_runs

RUNS = 10_000
BUDGET_SECONDS = 2.0


async def test_each_answer_returns_within_budget_on_ten_thousand_runs(
    session: AsyncSession, clock: FakeClock
) -> None:
    base = await seed_runs(session, clock, RUNS)
    await seed_busy(session, clock, base)
    answers = {
        "brief": brief(session, clock),
        "inbox": inbox(session),
        "health": health(session, clock),
    }
    for name, pending in answers.items():
        started = time.perf_counter()
        await pending
        elapsed = time.perf_counter() - started
        assert elapsed < BUDGET_SECONDS, f"{name} took {elapsed:.2f}s"
