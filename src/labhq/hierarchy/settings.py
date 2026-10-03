"""Hierarchy switches and caps, read from `LABHQ_*` environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HierarchySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_", extra="ignore")

    # Plan §5, rule 4: a new agent waits for a human unless the owner turns this off.
    approve_new_agents: bool = True
    # Agents under one manager, leads included. Provisional: plan §13 question 4 is open, so
    # this is a setting and a manager's `config["max_team_size"]` overrides it.
    max_team_size: int = Field(default=8, gt=0)
    # The adapter the CEO and the managers it assigns run on, unless the caller names one.
    org_adapter: str = "claude"
