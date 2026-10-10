"""Resolution order: request, agent, task kind, role, tool default, with unusable rows skipped."""

import logging

import pytest

from labhq.modelpolicy.policy import default_policy
from labhq.modelpolicy.resolve import TOOL_DEFAULT, resolve

OPUS, SONNET, HAIKU = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"


def pick(**overrides: object):  # type: ignore[no-untyped-def]
    arguments: dict[str, object] = {
        "request_model": None,
        "agent_model": None,
        "task_kind": None,
        "role": "worker",
        "unusable": {},
    }
    return resolve(default_policy(), **{**arguments, **overrides})  # type: ignore[arg-type]


def test_the_request_wins_over_everything() -> None:
    got = pick(request_model=OPUS, agent_model=SONNET, task_kind="summary")
    assert (got.model, got.source) == (OPUS, "request")


def test_the_agent_override_beats_the_task_kind() -> None:
    got = pick(agent_model=OPUS, task_kind="summary")
    assert (got.model, got.source) == (OPUS, "agent")
    # Effort still follows the policy row of the task.
    assert got.effort == "medium"


def test_the_task_kind_beats_the_role() -> None:
    got = pick(task_kind="summary", role="ceo")
    assert (got.model, got.effort, got.source) == (HAIKU, "medium", "task_kind:summary")


def test_the_role_applies_without_a_task_kind() -> None:
    got = pick(role="ceo")
    assert (got.model, got.effort, got.source) == (SONNET, "high", "role:ceo")


def test_nothing_known_leaves_the_tools_own_default() -> None:
    got = pick(role="stranger")
    assert (got.model, got.source) == (None, TOOL_DEFAULT)


def test_an_unusable_row_falls_through_to_the_next_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="labhq.modelpolicy.resolve"):
        got = pick(task_kind="summary", unusable={HAIKU: "seven_day_haiku is at 100% of the plan"})
    assert (got.model, got.source) == (SONNET, "role:worker")
    assert [(s.source, s.model) for s in got.skipped] == [("task_kind:summary", HAIKU)]
    assert "task_kind:summary" in caplog.text and "seven_day_haiku" in caplog.text


def test_an_explicit_request_is_not_skipped() -> None:
    assert pick(request_model=OPUS, unusable={OPUS: "capped"}).model == OPUS
