"""The push guard as an external hook command, on captured PreToolUse payloads."""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from labhq.guards.hook_command import DENY_EXIT_CODE, run

FIXTURES = Path(__file__).with_name("fixtures")


def invoke(payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "labhq.guards.hook_command"],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_entry_point_denies_git_push_on_a_captured_payload() -> None:
    result = invoke((FIXTURES / "pretooluse_git_push.json").read_text(encoding="utf-8"))

    assert result.returncode == DENY_EXIT_CODE == 2
    assert "git push" in result.stderr
    assert result.stdout == ""


def test_the_entry_point_allows_git_commit_on_a_captured_payload() -> None:
    result = invoke((FIXTURES / "pretooluse_git_commit.json").read_text(encoding="utf-8"))

    assert result.returncode == 0
    assert result.stdout == result.stderr == ""


def _code(payload: object) -> int:
    return run(io.StringIO(json.dumps(payload)), io.StringIO())


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "run_shell_command", "tool_input": {"command": "git push"}},
        {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 3"}},
        {"tool_name": "Bash", "tool_input": {}},
        ["not", "an", "object"],
    ],
    ids=["gemini-shell", "gh-merge", "no-command", "not-an-object"],
)
def test_publishing_and_unreadable_payloads_are_denied(payload: object) -> None:
    assert _code(payload) == DENY_EXIT_CODE


def test_unparsable_input_is_denied() -> None:
    assert run(io.StringIO("{not json"), io.StringIO()) == DENY_EXIT_CODE


def test_other_tools_are_left_alone() -> None:
    assert _code({"tool_name": "Edit", "tool_input": {"file_path": "a.py"}}) == 0
