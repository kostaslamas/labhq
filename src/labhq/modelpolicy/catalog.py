"""The models labhq knows, as data: a new model is a new row, never a code change.

IDs and prices are from the Claude API reference (platform.claude.com/docs/en/models,
checked 2026-10-10). IDs carry no date suffix. Prices are integer micro-USD per million
tokens (ADR 0002); Haiku 5.5 is priced for prompts up to 100K tokens, and the higher tier
above that is not modelled, so a cost estimate for a long prompt reads low.
"""

from dataclasses import dataclass

MICROS_PER_USD = 1_000_000


@dataclass(frozen=True)
class ModelInfo:
    id: str
    display_name: str
    # The plan windows of a model family are named after it (`seven_day_opus`).
    family: str
    input_micros_per_mtok: int
    output_micros_per_mtok: int
    # Haiku 5.5 answers 400 to `budget_tokens`, non-default sampling and an assistant
    # prefill, and has no server-side refusal fallback. Thinking is adaptive only.
    adaptive_only: bool = False


CATALOG: tuple[ModelInfo, ...] = (
    ModelInfo("claude-opus-5-5", "Opus 5.5", "opus", 4 * MICROS_PER_USD, 20 * MICROS_PER_USD),
    ModelInfo("claude-sonnet-5-5", "Sonnet 5.5", "sonnet", 2 * MICROS_PER_USD, 10 * MICROS_PER_USD),
    ModelInfo("claude-haiku-5-5", "Haiku 5.5", "haiku", 100_000, 500_000, adaptive_only=True),
    ModelInfo("claude-haiku-4-5", "Haiku 4.5", "haiku", MICROS_PER_USD, 5 * MICROS_PER_USD),
)

BY_ID: dict[str, ModelInfo] = {model.id: model for model in CATALOG}

EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")


def known(model_id: str) -> bool:
    return model_id in BY_ID


def info(model_id: str | None) -> ModelInfo | None:
    return BY_ID.get(model_id or "")


def estimate_micros(model_id: str, input_tokens: int, output_tokens: int) -> int | None:
    """What these tokens cost at the model's list price, or None for an unknown model."""
    model = info(model_id)
    if model is None:
        return None
    total = (
        input_tokens * model.input_micros_per_mtok + output_tokens * model.output_micros_per_mtok
    )
    return total // 1_000_000
