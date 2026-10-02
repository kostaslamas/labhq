"""The `rtk` PreToolUse hook: off with a warning when missing, rewriting when present."""

import logging
import stat
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import HookMatcher

from labhq.economy.rtk import RTK_MISSING, SHELL_TOOL, rewrite_command, rtk_hook

# A stand-in for `rtk rewrite`: filters `pytest` and `git` commands, declines the rest.
STUB_RTK = """#!/bin/sh
[ "$1" = rewrite ] || exit 2
case "$2" in
  pytest*|git*) printf 'rtk %s\\n' "$2" ;;
  *) exit 1 ;;
esac
"""


def install_stub(directory: Path, script: str = STUB_RTK) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "rtk"
    binary.write_text(script, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return binary


@pytest.fixture
def stub_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binary = install_stub(tmp_path / "bin")
    monkeypatch.setenv("PATH", str(binary.parent))
    return binary


def bash_input(command: str, tool_name: str = SHELL_TOOL) -> Any:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "transcript_path": "t",
        "cwd": "/work",
        "tool_name": tool_name,
        "tool_input": {"command": command, "description": "run tests"},
        "tool_use_id": "tu_1",
    }


async def call_hook(matcher: HookMatcher, hook_input: Any) -> Any:
    (callback,) = matcher.hooks
    return await callback(hook_input, "tu_1", {"signal": None})


def test_without_rtk_the_hook_is_off_and_a_warning_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with caplog.at_level(logging.WARNING, logger="labhq.economy.rtk"):
        hook = rtk_hook()
    assert not hook.enabled
    assert hook.matchers == []
    assert hook.hooks() == {}
    (warning,) = hook.warnings
    assert warning.code == RTK_MISSING
    assert warning.as_event_payload() == {"code": RTK_MISSING, "message": warning.message}
    assert "rtk is not on PATH" in caplog.text


def test_with_rtk_on_path_the_hook_matches_the_shell_tool(stub_on_path: Path) -> None:
    hook = rtk_hook()
    assert hook.enabled
    assert hook.binary == stub_on_path
    assert hook.warnings == ()
    (matcher,) = hook.hooks()["PreToolUse"]
    assert matcher.matcher == SHELL_TOOL


async def test_with_a_stub_rtk_the_hook_rewrites_the_command(stub_on_path: Path) -> None:
    (matcher,) = rtk_hook().matchers
    output = await call_hook(matcher, bash_input("pytest -q tests"))
    specific = output["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["updatedInput"] == {
        "command": "rtk pytest -q tests",
        "description": "run tests",
    }
    # The hook rewrites only; it never grants or denies permission.
    assert "permissionDecision" not in specific


async def test_commands_rtk_declines_run_unchanged(stub_on_path: Path) -> None:
    (matcher,) = rtk_hook().matchers
    assert await call_hook(matcher, bash_input("ls -la")) == {}


async def test_other_tools_are_left_alone(stub_on_path: Path) -> None:
    (matcher,) = rtk_hook().matchers
    assert await call_hook(matcher, bash_input("pytest", tool_name="Read")) == {}


async def test_an_empty_command_is_left_alone(stub_on_path: Path) -> None:
    (matcher,) = rtk_hook().matchers
    assert await call_hook(matcher, bash_input("   ")) == {}


async def test_an_echoed_command_is_not_a_rewrite(tmp_path: Path) -> None:
    binary = install_stub(tmp_path / "bin", '#!/bin/sh\nprintf "%s\\n" "$2"\n')
    assert await rewrite_command(binary, "make test") is None


async def test_a_broken_rtk_never_blocks_the_command(tmp_path: Path) -> None:
    binary = install_stub(tmp_path / "bin", "#!/nonexistent/interpreter\n")
    assert await rewrite_command(binary, "pytest") is None


async def test_a_hung_rtk_times_out_and_the_command_runs_unchanged(tmp_path: Path) -> None:
    # `exec` so the kill reaches the blocking process itself, not a parent shell.
    binary = install_stub(tmp_path / "bin", "#!/bin/sh\nexec cat\n")
    assert await rewrite_command(binary, "pytest", timeout=0.2) is None


async def test_rtk_gets_no_environment_beyond_path_and_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    binary = install_stub(tmp_path / "bin", '#!/bin/sh\nprintf "env:%s\\n" "$ANTHROPIC_API_KEY"\n')
    assert await rewrite_command(binary, "pytest") == "env:"
