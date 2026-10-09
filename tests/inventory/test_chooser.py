"""The analysis runner is chosen from installed, logged-in kinds with plan room, cheapest first."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db.models import UsageReading
from labhq.inventory.chooser import NoRunnerError, Runner, choose_runner, default_runners
from labhq.inventory.settings import InventorySettings
from tests.db.factories import project_agent_task

RUNNERS = {
    name: Runner(name, "tmux", {"agent": name}, name)
    for name in ("codex", "cursor-agent", "claude-code")
}
ORDER = ["cursor-agent", "codex", "claude-code"]


def logged_in(*names: str):
    return lambda argv, timeout: (0, "") if argv[0] in names else (1, "")


async def choose(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    *,
    original: set[str] = frozenset(),  # type: ignore[assignment]
    installed: tuple[str, ...] = ("codex", "cursor-agent", "claude-code"),
    login: tuple[str, ...] = ("codex", "cursor-agent", "claude-code"),
    **settings: object,
) -> str:
    async with sessions() as db:
        choice = await choose_runner(
            db,
            clock,
            InventorySettings(analysis_kind_order=ORDER, **settings),  # type: ignore[arg-type]
            original_tools=original,
            runners=RUNNERS,
            run=logged_in(*login),
            which=lambda name: name if name in installed else None,
        )
    return choice.runner.name


async def test_the_cheapest_logged_in_kind_runs_it(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    # codex is listed second but priced lower than the default.
    assert await choose(sessions, clock) == "codex"
    prices = {"codex": 9, "cursor-agent": 1}
    assert await choose(sessions, clock, price_per_million_tokens_micros=prices) == "cursor-agent"


async def test_kinds_that_are_not_installed_or_not_logged_in_are_skipped(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    assert await choose(sessions, clock, installed=("codex",), login=("codex",)) == "codex"
    with pytest.raises(
        NoRunnerError, match=r"cursor-agent: not installed.*claude-code: not installed"
    ):
        await choose(sessions, clock, installed=("codex",), login=(), original={"codex"})
    with pytest.raises(NoRunnerError, match="codex: not logged in"):
        await choose(sessions, clock, installed=("codex",), login=())


async def test_the_tool_that_made_the_sessions_is_skipped_by_default(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    assert await choose(sessions, clock, original={"codex"}) == "cursor-agent"


async def test_a_kind_at_its_plan_limit_is_skipped(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    async with sessions() as db:
        _, agent, _ = await project_agent_task(db, clock)
        db.add(
            UsageReading(
                agent_id=agent.id,
                agent_kind="codex",
                source="screen",
                unit="percent",
                window="day",
                value=95.0,
                created_at=clock.now(),
            )
        )
        await db.commit()

    assert await choose(sessions, clock) == "cursor-agent"


def test_a_local_model_is_a_runner_without_a_binary() -> None:
    assert default_runners()["ollama"] == Runner("ollama", "ollama")
    assert default_runners()["opencode"].config == {"agent": "opencode"}
