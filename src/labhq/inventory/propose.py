"""A proposed action per session, from a rule table: thresholds are settings, not code."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from labhq.inventory.model import Action, GitFacts, Proposal, SessionInfo, SessionState
from labhq.inventory.settings import InventorySettings


@dataclass(frozen=True)
class Context:
    session: SessionInfo
    git: GitFacts
    now: datetime
    settings: InventorySettings

    @property
    def idle(self) -> timedelta:
        return timedelta(seconds=self.session.idle_seconds or 0)

    @property
    def has_open_work(self) -> bool:
        return self.git.dirty_files > 0 or self.git.open_pr is not None


@dataclass(frozen=True)
class Rule:
    name: str
    applies: Callable[[Context], bool]
    action: Action
    reason: str


def _running(context: Context) -> bool:
    return context.session.pid is not None


def _stale_running(context: Context) -> bool:
    return _running(context) and context.idle >= timedelta(hours=context.settings.idle_close_hours)


def _live(context: Context) -> bool:
    return _running(context)


def _recent_with_work(context: Context) -> bool:
    return context.has_open_work and context.idle < timedelta(days=context.settings.history_days)


def _recent(context: Context) -> bool:
    return context.idle < timedelta(days=context.settings.history_days)


# The first rule that applies wins. Closing never loses the conversation: it stays saved.
RULES: tuple[Rule, ...] = (
    Rule(
        "waiting",
        lambda c: c.session.state is SessionState.WAITING,
        Action.CONTINUE,
        "it waits for your input",
    ),
    Rule(
        "stale-running",
        _stale_running,
        Action.CLOSE,
        "it has been quiet for a long time; the conversation stays saved",
    ),
    Rule("live", _live, Action.CONTINUE, "it is running; labhq can take it over as manager"),
    Rule(
        "recent-work",
        _recent_with_work,
        Action.CONTINUE,
        "the project has uncommitted changes or an open pull request",
    ),
    Rule("recent", _recent, Action.CONTINUE, "its last activity is recent"),
)
FALLBACK = Rule("old", lambda c: True, Action.HISTORY, "nothing happened in it for a long time")


def propose(
    session: SessionInfo, git: GitFacts, now: datetime, settings: InventorySettings
) -> Proposal:
    context = Context(session, git, now, settings)
    rule = next((r for r in RULES if r.applies(context)), FALLBACK)
    return Proposal(rule.action, rule.reason)
