"""What task tools show an agent, read from `LABHQ_WORK_*`."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_WORK_", extra="ignore")

    # How many of a task's own latest reports `task_overview` lists. Children always show
    # their latest one, so a parent reads every result in a single call.
    overview_reports: int = Field(default=5, gt=0)


@lru_cache(maxsize=1)
def get_work_settings() -> WorkSettings:
    return WorkSettings()
