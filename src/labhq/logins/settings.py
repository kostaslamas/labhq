"""How long a login request waits for a link and how often the program looks again."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LoginSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_LOGIN_", extra="ignore")

    # How long the tool gets to print its login link after its login command starts.
    url_wait_seconds: float = Field(default=20.0, gt=0)
    poll_seconds: float = Field(default=1.0, gt=0)
    status_timeout_seconds: float = Field(default=15.0, gt=0)
    # A run that stopped on a login screen is looked at again for this long.
    blocked_run_window_seconds: float = Field(default=900.0, gt=0)


@lru_cache(maxsize=1)
def get_login_settings() -> LoginSettings:
    return LoginSettings()
