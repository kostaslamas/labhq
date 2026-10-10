"""Model, effort and thinking options for a Claude run, kept inside what each model accepts.

Haiku 5.5 answers 400 to `budget_tokens`, to non-default `temperature`, `top_p` and `top_k`,
and to an assistant prefill; its thinking is adaptive only. For such a model the options are
stripped here, with a warning, so a leftover agent setting cannot fail the run.
"""

import logging
from collections.abc import Mapping
from typing import Any

from claude_agent_sdk.types import ThinkingConfigAdaptive

from labhq.modelpolicy.catalog import info

log = logging.getLogger(__name__)

# Flags and settings that carry sampling or a prefill; none is valid on an adaptive-only model.
SAMPLING_ARGS = frozenset({"temperature", "top-p", "top-k", "top_p", "top_k", "prefill"})
OUTPUT_TOKENS_VARIABLE = "CLAUDE_CODE_MAX_OUTPUT_TOKENS"


def model_options(
    model: str | None,
    *,
    effort: str | None,
    max_output_tokens: int | None,
    max_thinking_tokens: int | None,
    extra_args: Mapping[str, str | None],
) -> tuple[dict[str, Any], dict[str, str]]:
    """The `ClaudeAgentOptions` keys for the model, and environment variables to add."""
    options: dict[str, Any] = {"model": model, "effort": effort}
    args = dict(extra_args)
    env: dict[str, str] = {}
    if max_output_tokens is not None:
        env[OUTPUT_TOKENS_VARIABLE] = str(max_output_tokens)
    known = info(model)
    if known is not None and known.adaptive_only:
        dropped = [name for name in args if name.lstrip("-") in SAMPLING_ARGS]
        if max_thinking_tokens is not None or dropped:
            log.warning("%s takes adaptive thinking only; dropped %s", model, dropped or "budget")
        args = {name: value for name, value in args.items() if name not in dropped}
        options["thinking"] = ThinkingConfigAdaptive(type="adaptive")
        max_thinking_tokens = None
    options["max_thinking_tokens"] = max_thinking_tokens
    options["extra_args"] = args
    return options, env
