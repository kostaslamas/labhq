"""The model policy: a role or task kind maps to a model and an effort.

The table is configuration. It lives in the `program_state` row `model_policy`, and an
unknown model ID or effort is refused when it is saved. Rows not stored fall back to the
defaults here.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

from labhq.modelpolicy.catalog import EFFORTS, known

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"

ROLE_KEYS: tuple[str, ...] = ("ceo", "manager", "head", "lead", "worker", "it")
TASK_KINDS: tuple[str, ...] = ("project_analysis", "summary", "check")
KEYS: tuple[str, ...] = (*ROLE_KEYS, *TASK_KINDS)

# Thinking is adaptive and on by default, so a short route needs room for it besides the
# answer; a small cap would end the turn inside the thinking block.
SUMMARY_OUTPUT_TOKENS = 16_000


class PolicyError(ValueError):
    """The table was refused; nothing was saved."""


class PolicyRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    effort: str
    max_output_tokens: int | None = Field(default=None, gt=0)

    @field_validator("model")
    @classmethod
    def _known_model(cls, value: str) -> str:
        if not known(value):
            raise ValueError(f"unknown model {value!r}")
        return value

    @field_validator("effort")
    @classmethod
    def _known_effort(cls, value: str) -> str:
        if value not in EFFORTS:
            raise ValueError(f"unknown effort {value!r}; valid: {', '.join(EFFORTS)}")
        return value


def _row(model: str, effort: str, cap: int | None = None) -> PolicyRow:
    return PolicyRow(model=model, effort=effort, max_output_tokens=cap)


DEFAULT_ROWS: Mapping[str, PolicyRow] = {
    "ceo": _row(SONNET, "high"),
    "manager": _row(SONNET, "high"),
    "head": _row(SONNET, "high"),
    "lead": _row(SONNET, "high"),
    "worker": _row(SONNET, "medium"),
    "it": _row(SONNET, "medium"),
    "project_analysis": _row(SONNET, "medium"),
    "summary": _row(HAIKU, "medium", SUMMARY_OUTPUT_TOKENS),
    "check": _row(HAIKU, "medium", SUMMARY_OUTPUT_TOKENS),
}


@dataclass(frozen=True)
class ModelPolicy:
    rows: Mapping[str, PolicyRow]

    def row(self, key: str | None) -> PolicyRow | None:
        return self.rows.get(key) if key else None


def build(rows: Mapping[str, object]) -> ModelPolicy:
    """Validate `rows` laid over the defaults; raise `PolicyError` naming the bad key."""
    merged = dict(DEFAULT_ROWS)
    for key, value in rows.items():
        if key not in KEYS:
            raise PolicyError(f"unknown role or task kind {key!r}; valid: {', '.join(KEYS)}")
        try:
            merged[key] = PolicyRow.model_validate(value)
        except ValueError as error:
            raise PolicyError(f"{key}: {error}") from None
    return ModelPolicy(merged)


def default_policy() -> ModelPolicy:
    return ModelPolicy(dict(DEFAULT_ROWS))
