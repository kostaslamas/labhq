"""Auth settings, read from `LABHQ_AUTH_*` environment variables and `LABHQ_PUBLIC_URL`.

Without `LABHQ_PUBLIC_URL`, the address `labhq serve` persisted in the data directory is used.
"""

from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from labhq.auth.public_url import load_public_url
from labhq.settings import Settings

LOCAL_FALLBACK_URL = "http://localhost:8787"


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LABHQ_AUTH_", extra="ignore", populate_by_name=True
    )

    # The stable URL the owner approves from on a phone. A passkey is bound to its host, so
    # this is enrolled once separately from `localhost`.
    public_url: str | None = Field(default=None, validation_alias="LABHQ_PUBLIC_URL")
    # Hosts that count as "this machine" on any port; their passkeys never work elsewhere.
    local_hosts: tuple[str, ...] = ("localhost",)
    # How long an enrollment link from `labhq passkey enroll` stays valid; it works once.
    enrollment_ttl_seconds: int = Field(default=600, gt=0)
    # The step-up window: how long an issued challenge may wait for its assertion.
    challenge_ttl_seconds: int = Field(default=120, gt=0)
    # A session ends after this long without a request.
    session_idle_seconds: int = Field(default=8 * 3600, gt=0)
    # A session ends this long after sign-in, however active it is.
    session_absolute_seconds: int = Field(default=30 * 24 * 3600, gt=0)
    # Name of the HttpOnly session cookie.
    session_cookie: str = "labhq_session"

    @field_validator("public_url")
    @classmethod
    def _origin_only(cls, value: str | None) -> str | None:
        if not value:
            return None
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("LABHQ_PUBLIC_URL must be an http(s) URL with a host")
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def link_base(self) -> str:
        """Where `labhq passkey enroll` points when no URL is given."""
        return self.public_url or LOCAL_FALLBACK_URL


def get_auth_settings() -> AuthSettings:
    # Not cached: tests change the environment between apps.
    settings = AuthSettings()
    if settings.public_url is not None:
        return settings
    # The shell variable wins; without it, the address the running program persisted.
    remembered = load_public_url(Settings().data_dir)
    if remembered is None:
        return settings
    return AuthSettings(public_url=remembered)
