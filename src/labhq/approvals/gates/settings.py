"""Gate configuration, read from `LABHQ_GATE_*`. Nothing about a particular gate is in code."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GateSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_GATE_", extra="ignore")

    # The adapter registration to use; the generic HTTP gate is the only built-in.
    kind: str = "http"
    # Recorded as the decider (`gate:<name>`), so the audit trail says which gate answered.
    name: str = "gate"
    base_url: str | None = None
    # SecretStr keeps the token out of reprs, tracebacks and validation errors of this object.
    token: SecretStr | None = None
    token_header: str = "X-Gate-Token"
    request_path: str = "/internal/request"
    status_path: str = "/internal/status/{id}"
    timeout_seconds: float = Field(default=10.0, gt=0)
    # Comma-separated `via` values that count as a passkey proof. `password` is not one.
    passkey_proofs: str = "passkey,face_id,webauthn"

    @property
    def configured(self) -> bool:
        return bool(self.base_url) and self.token is not None

    @property
    def proofs(self) -> frozenset[str]:
        return frozenset(
            part.strip().lower() for part in self.passkey_proofs.split(",") if part.strip()
        )
