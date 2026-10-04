"""labhq's capped share of each plan window (ADR 0003, plan §7 rule 7).

For each window the readings of an agent kind report, the latest valid reading stands until
its `resets_at`. At `plan_usage_warn_percent` the owner is warned; from
`plan_usage_stop_percent` no new run of that agent kind starts until the window resets. A
limit notice read from the screen is a reading of 100% in the `limit_notice` window, so it
holds the same way. Readings cover the whole account, the owner's own use included.

The check flushes notifications but never commits: the caller owns the transaction.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.budgets import Decision, stricter
from labhq.clock import Clock
from labhq.db.models import Agent, UsageReading
from labhq.notify import enqueue as notify
from labhq.usage.schema import UsageUnit
from labhq.usage.settings import UsageSettings, get_usage_settings

LIMIT_WINDOW = "limit_notice"
FALLBACK_KEY = "fallback_agent"
FALLBACK_ADAPTER_KEY = "fallback_adapter"


def _tmux_kind(config: Mapping[str, Any]) -> str | None:
    kind = config.get("agent")
    return kind if isinstance(kind, str) and kind else None


# Adapters that run several CLIs name the CLI in `agents.config`; any other adapter is
# its own kind.
KIND_READERS: dict[str, Callable[[Mapping[str, Any]], str | None]] = {"tmux": _tmux_kind}


def agent_kind(adapter: str, config: Mapping[str, Any]) -> str:
    reader = KIND_READERS.get(adapter)
    kind = reader(config) if reader is not None else None
    return kind or adapter


def fallback_kind(config: Mapping[str, Any]) -> str | None:
    value = config.get(FALLBACK_KEY)
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class WindowCheck:
    window: str
    used_percent: float
    resets_at: datetime | None
    decision: Decision


@dataclass(frozen=True)
class PlanCheck:
    agent_kind: str
    decision: Decision
    windows: tuple[WindowCheck, ...]

    @property
    def resumes_at(self) -> datetime | None:
        """When the latest stopping window resets; None when nothing stops or it is unknown."""
        stops = [w.resets_at for w in self.windows if w.decision is Decision.STOP]
        if not stops or None in stops:
            return None
        return max(at for at in stops if at is not None)


def decide(used_percent: float, settings: UsageSettings) -> Decision:
    if used_percent >= settings.plan_usage_stop_percent:
        return Decision.STOP
    if used_percent >= settings.plan_usage_warn_percent:
        return Decision.WARN
    return Decision.ALLOW


async def check_kind(
    db: AsyncSession, kind: str, clock: Clock, settings: UsageSettings | None = None
) -> PlanCheck:
    """The plan decision for one agent kind, from its latest valid reading per window."""
    settings = settings or get_usage_settings()
    now = clock.now()
    rows = await db.scalars(
        select(UsageReading)
        .where(
            UsageReading.agent_kind == kind,
            UsageReading.unit == UsageUnit.PERCENT.value,
            UsageReading.value.is_not(None),
            or_(UsageReading.resets_at.is_(None), UsageReading.resets_at > now),
        )
        .order_by(UsageReading.created_at.desc(), UsageReading.id.desc())
    )
    latest: dict[str, UsageReading] = {}
    for row in rows:
        latest.setdefault(row.window or "", row)
    windows = tuple(
        WindowCheck(window, row.value, row.resets_at, decide(row.value, settings))
        for window, row in sorted(latest.items())
        if row.value is not None
    )
    return PlanCheck(kind, stricter(*(w.decision for w in windows)), windows)


async def check_agent(
    db: AsyncSession,
    agent: Agent,
    clock: Clock,
    settings: UsageSettings | None = None,
    *,
    kind: str | None = None,
) -> PlanCheck:
    """Check the agent's kind (or `kind`) and tell the owner about a warning or a stop."""
    result = await check_kind(db, kind or agent_kind(agent.adapter, agent.config), clock, settings)
    for window in result.windows:
        if window.decision is not Decision.ALLOW:
            await _announce(db, result.agent_kind, window, clock.now())
    return result


async def _announce(db: AsyncSession, kind: str, window: WindowCheck, now: datetime) -> None:
    # One notification per kind, window, level and window period.
    period = window.resets_at.isoformat() if window.resets_at else "open"
    resets = f" until {window.resets_at:%Y-%m-%d %H:%M} UTC" if window.resets_at else ""
    stopping = window.decision is Decision.STOP
    await notify(
        db,
        kind="plan_usage",
        subject=f"agent-kind:{kind}",
        title=f"{kind}: {window.window} at {window.used_percent:g}%",
        body=(
            f"No new {kind} runs start{resets}."
            if stopping
            else f"{kind} has used {window.used_percent:g}% of its {window.window} window."
        ),
        idempotency_key=f"plan-usage:{kind}:{window.window}:{window.decision}:{period}",
        now=now,
    )
