"""Who runs an analysis: an installed, logged-in kind with plan room, cheapest first."""

import shutil
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters.kinds import agent_choices
from labhq.adapters.tmux import AgentKinds, default_kinds
from labhq.budgets import Decision
from labhq.clock import Clock
from labhq.inventory.login import StatusRunner, login_of, run_status
from labhq.inventory.settings import InventorySettings
from labhq.usage import check_kind

Which = Callable[[str], str | None]


@dataclass(frozen=True)
class Runner:
    """An agent kind that can run an analysis: the adapter and config its agent row gets."""

    name: str
    adapter: str
    config: Mapping[str, Any] = field(default_factory=dict)
    binary: str | None = None


@dataclass(frozen=True)
class Choice:
    runner: Runner
    account: str | None
    price_micros: int


class NoRunnerError(RuntimeError):
    """No kind is logged in with plan room; the message says what was skipped and why."""


def default_runners() -> dict[str, Runner]:
    runners = {c.name: Runner(c.name, c.adapter, dict(c.config), c.binary) for c in agent_choices()}
    # A local model: no login, no plan, no binary of labhq's to look for.
    runners["ollama"] = Runner("ollama", "ollama")
    return runners


async def choose_runner(
    db: AsyncSession,
    clock: Clock,
    settings: InventorySettings,
    *,
    original_tools: Collection[str],
    runners: Mapping[str, Runner] | None = None,
    kinds: AgentKinds = default_kinds,
    run: StatusRunner = run_status,
    which: Which = shutil.which,
) -> Choice:
    pool = runners if runners is not None else default_runners()
    skipped: list[str] = []
    eligible: list[Choice] = []
    for name in settings.analysis_kind_order:
        runner = pool.get(name)
        if runner is None:
            skipped.append(f"{name}: unknown kind")
        elif name in original_tools and not settings.allow_original_tool:
            skipped.append(f"{name}: made the sessions")
        elif runner.binary is not None and which(runner.binary) is None:
            skipped.append(f"{name}: not installed")
        else:
            account, reason = await _ready(db, clock, settings, runner, kinds, run)
            if reason is not None:
                skipped.append(f"{name}: {reason}")
                continue
            price = settings.price_per_million_tokens_micros.get(
                name, settings.default_price_per_million_micros
            )
            eligible.append(Choice(runner, account, price))
    if not eligible:
        raise NoRunnerError("no kind can run the analysis (" + "; ".join(skipped) + ")")
    # Stable: kinds of equal price keep the order the owner listed them in.
    return min(eligible, key=lambda choice: choice.price_micros)


async def _ready(
    db: AsyncSession,
    clock: Clock,
    settings: InventorySettings,
    runner: Runner,
    kinds: AgentKinds,
    run: StatusRunner,
) -> tuple[str | None, str | None]:
    account = None
    if runner.name not in settings.no_login_kinds:
        if runner.name not in kinds.names():
            return None, "no login check"
        logged_in, account = login_of(kinds.get(runner.name), run, settings.command_timeout_seconds)
        if logged_in is not True:
            return None, "not logged in" if logged_in is False else "login unknown"
    plan = await check_kind(db, runner.name, clock)
    if plan.decision is Decision.STOP:
        return None, "plan limit reached"
    return account, None
