"""How the Call Center agent row is first created, from `LABHQ_CALLCENTER_*` variables.

These are defaults for a row that does not exist yet. Once it exists the row is the data:
moving the agent to another adapter, model or budget is an edit to the row, not code.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CallAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_CALLCENTER_", extra="ignore")

    # The SDK adapter until the tmux adapter lands (ADR 0004, Phase 2 amendment).
    agent_adapter: str = "claude"
    agent_model: str | None = None
    # Its own budget, per budget period, so a chatty call cannot eat the workers' money.
    agent_budget_micros: int = Field(default=2_000_000, ge=0)
    # Reading needs a few tool calls; routing needs one more.
    agent_max_turns: int = Field(default=12, gt=0)


@lru_cache(maxsize=1)
def get_call_agent_settings() -> CallAgentSettings:
    return CallAgentSettings()
