"""The four agents as data: their templates, launch integrations and recorded sources."""

import json
import shlex
from pathlib import Path

import pytest

from labhq.adapters import RunRequest, default_registry
from labhq.adapters.tmux import (
    AgentKinds,
    SessionIdSource,
    TmuxAdapter,
    TmuxServer,
    UnknownAgentKindError,
    UsageSource,
    default_kinds,
)
from labhq.adapters.tmux.agents import LaunchContext, claude_settings, codex_notify
from labhq.clock import FakeClock

CONTEXT = LaunchContext(
    python="/venv/bin/python",
    signal_path=Path("/data/tmux/runs/run-7/turn-end.json"),
    statusline_path=Path("/data/tmux/runs/run-7/statusline.json"),
    guard_hook="/venv/bin/python -m labhq.guards.hook_command",
)


def test_the_four_agents_are_registered_with_their_sources() -> None:
    assert default_kinds.names() == ["aider", "claude-code", "codex", "gemini"]
    for name in default_kinds.names():
        kind = default_kinds.get(name)
        assert "checked 2026-10-03" in kind.source
        assert "{prompt}" in kind.start
        assert kind.interrupt_keys


def test_only_claude_code_reads_usage_from_the_statusline_and_installs_the_hook() -> None:
    by_source = {name: default_kinds.get(name).usage_source for name in default_kinds.names()}
    hooked = [name for name in default_kinds.names() if default_kinds.get(name).hooks]

    assert by_source["claude-code"] is UsageSource.STATUSLINE
    assert {by_source[n] for n in ("codex", "gemini", "aider")} == {UsageSource.SCREEN}
    assert hooked == ["claude-code"]


def test_claude_settings_carry_the_statusline_turn_signal_and_push_guard() -> None:
    flag, value = claude_settings(CONTEXT)
    settings = json.loads(value)

    assert flag == "--settings"
    assert shlex.split(settings["statusLine"]["command"])[-2:] == [
        "statusline",
        str(CONTEXT.statusline_path),
    ]
    (stop,) = settings["hooks"]["Stop"]
    assert shlex.split(stop["hooks"][0]["command"])[-2:] == ["turn", str(CONTEXT.signal_path)]
    (guard,) = settings["hooks"]["PreToolUse"]
    assert guard["matcher"] == "Bash"
    assert guard["hooks"][0]["command"] == CONTEXT.guard_hook


def test_codex_notify_runs_the_signal_command() -> None:
    flag, value = codex_notify(CONTEXT)
    key, _, program = value.partition("=")

    assert (flag, key) == ("-c", "notify")
    assert json.loads(program)[-2:] == ["turn", str(CONTEXT.signal_path)]


def _argv(kind: str, resume: str | None, tmp_path: Path) -> list[str]:
    server = TmuxServer(socket="unused", state_dir=tmp_path, binary="/usr/bin/tmux")
    adapter = TmuxAdapter(server=server, kinds=default_kinds, clock=FakeClock(), python="py")
    request = RunRequest(prompt="Fix it", cwd=tmp_path, resume_session_id=resume)
    return adapter._argv(default_kinds.get(kind), request, tmp_path)


def test_claude_code_starts_with_an_assigned_session_and_its_settings(tmp_path: Path) -> None:
    argv = _argv("claude-code", None, tmp_path)

    assert argv[0] == "claude"
    assert argv[1] == "--settings"
    assert argv[-1] == "Fix it"
    assert argv[argv.index("--session-id") + 1].count("-") == 4


def test_a_stored_session_of_the_same_kind_is_resumed(tmp_path: Path) -> None:
    assert _argv("codex", "codex:0199a213", tmp_path)[-3:] == [
        "--dangerously-bypass-approvals-and-sandbox",
        "0199a213",
        "Fix it",
    ]
    assert "--resume" in _argv("gemini", "gemini:abc", tmp_path)
    assert "--restore-chat-history" in _argv("aider", "aider:.aider.chat.history.md", tmp_path)


def test_a_session_of_another_kind_starts_afresh(tmp_path: Path) -> None:
    argv = _argv("claude-code", "codex:0199a213", tmp_path)

    assert "--resume" not in argv
    assert "0199a213" not in argv


def test_session_id_sources_cover_assigned_discovered_and_fixed() -> None:
    sources = {default_kinds.get(n).session_id for n in default_kinds.names()}

    assert sources == set(SessionIdSource)


def test_an_unknown_kind_is_an_error() -> None:
    with pytest.raises(UnknownAgentKindError):
        AgentKinds().get("nope")


def test_the_tmux_adapter_is_registered_next_to_claude() -> None:
    assert {"claude", "tmux"} <= set(default_registry.adapter_keys())
