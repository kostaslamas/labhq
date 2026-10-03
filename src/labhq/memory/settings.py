"""Who keeps memory and how much, read from `LABHQ_MEMORY_*` environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MemorySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_", extra="ignore")

    # Long-lived roles (plan §2). Workers are ephemeral and start every run blank.
    # `agents.config["memory"]` overrides this per agent.
    memory_roles: frozenset[str] = frozenset({"ceo", "manager", "lead"})
    # Memory is read into every prompt, so its size is paid on every run.
    memory_max_chars: int = Field(default=4000, gt=0)


@lru_cache(maxsize=1)
def get_memory_settings() -> MemorySettings:
    return MemorySettings()
