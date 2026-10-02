"""Budget thresholds and period, read from `LABHQ_BUDGET_*` environment variables."""

from functools import lru_cache
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from labhq.budgets.periods import BudgetPeriod


class BudgetSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_BUDGET_", extra="ignore")

    # Whole percentages keep the comparison in integers: spent * 100 >= budget * percent.
    warn_percent: int = Field(default=80, gt=0)
    stop_percent: int = Field(default=100, gt=0)
    period: BudgetPeriod = BudgetPeriod.MONTH

    @model_validator(mode="after")
    def _warn_before_stop(self) -> Self:
        if self.warn_percent > self.stop_percent:
            raise ValueError("warn_percent must not exceed stop_percent")
        return self


@lru_cache(maxsize=1)
def get_budget_settings() -> BudgetSettings:
    return BudgetSettings()
