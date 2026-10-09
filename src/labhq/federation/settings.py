"""How a downstream instance reaches its upstream. Environment only: the key is never stored."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class FederationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_FEDERATION_", extra="ignore")

    # The upstream's public URL (its exposure setting), without the `/api` path.
    upstream_url: str | None = None
    # The pairing key `labhq federation invite` printed here and `add` registered upstream.
    upstream_key: SecretStr | None = None
    # How orders from the upstream are labelled to this instance's CEO.
    upstream_name: str = Field(default="upstream", min_length=1, max_length=100)
    request_timeout_seconds: float = Field(default=20.0, gt=0)
    # Upstream side, A2A nodes: node name -> the key its `invite` printed. Only the hash is
    # stored in the database, and sending an order needs the key itself, so it comes from here
    # like the downstream's own key does. A JSON object: {"lab-b": "lhqf_..."}.
    node_keys: dict[str, SecretStr] = Field(default_factory=dict)


@lru_cache(maxsize=1)
def get_federation_settings() -> FederationSettings:
    return FederationSettings()
