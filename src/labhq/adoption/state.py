"""What the engine remembers about an adopted manager, kept in `agents.config["adoption"]`."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from labhq.db.models import Agent

STATE_KEY = "adoption"


class AdoptionState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str
    cwd: str
    repo: str
    tmux_session: str
    state_dir: str
    original_pid: int | None = None
    # The conversation the continued agent reported; None until it reports one.
    session_id: str | None = None
    uncommitted: list[str] = []
    # Fingerprint of the main checkout the last time the owner was told about it.
    baseline: str
    # Digests of the last turn signal and statusline document the checks handled.
    signal: str | None = None
    statusline: str | None = None
    # Screen lines already scanned for a compaction notice.
    screen_lines: int = 0
    # Kinds without a turn signal: the screen's digest, when it last changed, and whether
    # it changed since the last turn end.
    screen: str | None = None
    changed_at: datetime | None = None
    turn_open: bool = False
    # A status request is outstanding: one is sent per run of turns without an update.
    status_requested: bool = False
    # Rules owed to the agent while the plan cap held labhq's messages back.
    rules_due: bool = False


def state_of(agent: Agent) -> AdoptionState | None:
    raw = agent.config.get(STATE_KEY)
    return AdoptionState.model_validate(raw) if isinstance(raw, dict) else None


def store_state(agent: Agent, state: AdoptionState) -> None:
    # A new dict, so SQLAlchemy sees the JSON column change.
    config: dict[str, Any] = dict(agent.config)
    config[STATE_KEY] = state.model_dump(mode="json")
    agent.config = config
