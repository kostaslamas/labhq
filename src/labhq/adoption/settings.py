"""Adoption settings, from `LABHQ_ADOPT_*` variables. Timings are data, not constants."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AdoptionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_ADOPT_", extra="ignore")

    # Words put before the continued agent's command, for example a bubblewrap invocation
    # ending in `--` (plan §5, rule 6). Empty means none, and the confirmation warns.
    sandbox: list[str] = Field(default_factory=list)
    # The owner's tmux server, where an agent to adopt may run; None is tmux's default.
    owner_tmux_socket: str | None = None
    poll_seconds: float = Field(default=1.0, gt=0)
    # The original agent's turn has ended once its screen (or, outside tmux, its CPU time
    # and child processes) stayed the same this long.
    quiescence_seconds: float = Field(default=10.0, gt=0)
    turn_timeout_seconds: float = Field(default=3600.0, gt=0)
    # SIGTERM first; SIGKILL when the process outlives this.
    end_timeout_seconds: float = Field(default=10.0, gt=0)
    # The continued agent is ready for the first message once its screen is quiet this long.
    ready_seconds: float = Field(default=3.0, gt=0)
    ready_timeout_seconds: float = Field(default=120.0, gt=0)
    session_wait_seconds: float = Field(default=30.0, ge=0)


@lru_cache(maxsize=1)
def get_adoption_settings() -> AdoptionSettings:
    return AdoptionSettings()
