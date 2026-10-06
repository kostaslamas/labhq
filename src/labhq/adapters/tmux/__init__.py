"""The `tmux` adapter: Claude Code, Codex CLI, Gemini CLI, Aider or any CLI agent (ADR 0003)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from labhq.adapters.tmux.adapter import TmuxAdapter, TmuxAgentConfig, split_session
from labhq.adapters.tmux.agents import (
    AgentKind,
    AgentKinds,
    RulesInjection,
    SessionIdSource,
    TurnEnd,
    UnknownAgentKindError,
    UsageSource,
    default_kinds,
)
from labhq.adapters.tmux.idle import IdleSuspender
from labhq.adapters.tmux.server import TmuxError, TmuxMissingError, TmuxServer
from labhq.clock import SystemClock
from labhq.settings import get_settings


class TmuxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_TMUX_", extra="ignore")

    # The private server's socket: `tmux -L labhq attach -t run-<id>` watches a run.
    socket: str = "labhq"
    # A persistent pane (the CEO's) idle this long has its CLI process stopped to give the
    # RAM back; its session id is kept and the next turn resumes it. 0 never stops one.
    idle_suspend_seconds: int = Field(default=1800, ge=0)


@lru_cache(maxsize=1)
def get_tmux_settings() -> TmuxSettings:
    return TmuxSettings()


def default_tmux_adapter() -> TmuxAdapter:
    server = TmuxServer(
        socket=get_tmux_settings().socket, state_dir=get_settings().data_dir / "tmux"
    )
    return TmuxAdapter(
        server=server,
        kinds=default_kinds,
        clock=SystemClock(),
        owned_root=get_settings().data_dir,
    )


def default_idle_suspender() -> IdleSuspender | None:
    """None when tmux is not installed: there is no pane to suspend."""
    try:
        server = TmuxServer(
            socket=get_tmux_settings().socket, state_dir=get_settings().data_dir / "tmux"
        )
    except TmuxMissingError:
        return None
    return IdleSuspender(
        server, SystemClock(), idle_seconds=get_tmux_settings().idle_suspend_seconds
    )


__all__ = [
    "AgentKind",
    "AgentKinds",
    "IdleSuspender",
    "RulesInjection",
    "SessionIdSource",
    "TmuxAdapter",
    "TmuxAgentConfig",
    "TmuxError",
    "TmuxMissingError",
    "TmuxServer",
    "TmuxSettings",
    "TurnEnd",
    "UnknownAgentKindError",
    "UsageSource",
    "default_idle_suspender",
    "default_kinds",
    "default_tmux_adapter",
    "get_tmux_settings",
    "split_session",
]
