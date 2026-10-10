"""What the Claude adapter sends for a model: effort, adaptive thinking, no Haiku 5.5 400s."""

import logging

import pytest

from labhq.adapters import ClaudeAdapter, RunRequest
from labhq.adapters.contract import run_once
from labhq.db.enums import RunStatus
from labhq.runs.status import status_for
from tests.adapters.stub_sdk import CLI_PATH, StubScript, result_message, stub_claude

HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"
LEGACY = {
    "max_thinking_tokens": 5000,
    "extra_args": {
        "temperature": "0.2",
        "top-p": "0.5",
        "top_k": "3",
        "prefill": "{",
        "debug": None,
    },
}


def options_for(model: str, **config: object):  # type: ignore[no-untyped-def]
    request = RunRequest(
        prompt="hi", model=model, effort="low", max_output_tokens=16000, config=config
    )
    return ClaudeAdapter(cli_path=CLI_PATH, environ={}).options_for(request)


def test_the_resolved_model_and_effort_are_sent() -> None:
    options = options_for(SONNET)
    assert (options.model, options.effort) == (SONNET, "low")
    assert options.env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "16000"


def test_haiku_55_never_gets_a_thinking_budget_sampling_or_prefill(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        options = options_for(HAIKU, **LEGACY)
    assert options.model == HAIKU
    assert options.thinking == {"type": "adaptive"}
    assert options.max_thinking_tokens is None
    assert options.extra_args == {"debug": None}
    assert "adaptive thinking only" in caplog.text


def test_other_models_keep_what_the_agent_configured() -> None:
    options = options_for(SONNET, **LEGACY)
    assert options.max_thinking_tokens == 5000
    assert "temperature" in options.extra_args


def test_the_agent_override_is_used_when_no_policy_chose() -> None:
    request = RunRequest(prompt="hi", config={"model": SONNET})
    assert ClaudeAdapter(cli_path=CLI_PATH, environ={}).options_for(request).model == SONNET


async def test_a_refusal_is_a_failed_run_with_the_reason_never_an_empty_success() -> None:
    script = StubScript(messages=[], result_overrides={"stop_reason": "refusal", "result": ""})
    adapter = stub_claude(script)()
    _, result = await run_once(adapter, RunRequest(prompt="hi", model=HAIKU))
    assert result.is_error
    assert result.subtype == "error_refusal"
    assert any("refused" in error for error in result.errors)
    assert status_for(result) is RunStatus.FAILED


def test_a_normal_result_stays_a_success() -> None:
    from labhq.adapters.claude_messages import to_result

    result = to_result(result_message("s", stop_reason="end_turn"), None)
    assert not result.is_error and status_for(result) is RunStatus.SUCCEEDED
