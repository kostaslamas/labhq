"""What the owner alone decides about the CEO, read from `LABHQ_CEO_*` variables.

No tool writes these. The CEO runs on the owner's machine, so the one lever it must not hold
is the one that bounds what it may spend.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CeoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_CEO_", extra="ignore")

    # The most the CEO may set as any one agent's or project's budget, in micro-USD. Unset
    # means the owner has not delegated budgets yet, so `set_budget` refuses everything.
    budget_ceiling_micros: int | None = Field(default=None, gt=0)
    # How many directory levels `discover_projects` looks below the folder it is given.
    discovery_depth: int = Field(default=3, ge=1)
    # The most folders and sessions one `discover_projects` answer lists.
    discovery_limit: int = Field(default=100, gt=0)


@lru_cache(maxsize=1)
def get_ceo_settings() -> CeoSettings:
    return CeoSettings()
