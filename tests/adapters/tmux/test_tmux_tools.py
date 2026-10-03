"""Engine tools reach an agent in tmux as stdio MCP servers its CLI starts as children.

A run agent's engine tools (`labhq mcp agent --run N`) are an addition, attached where the
CLI takes a stdio server. A run's own tools (the Call Center's) replace the built-in ones,
so only a CLI that can drop its shell and file tools may run them.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from labhq.adapters import AdapterError, AgentTool, RunRequest
from labhq.adapters.tmux import TmuxAdapter, TmuxServer, default_kinds
from labhq.adapters.tmux.tools import MCP_CONFIG_FILE, TOOL_LAUNCHES
from labhq.clock import FakeClock

ENVIRON = {"PATH": "/usr/bin", "LABHQ_DATA_DIR": "/data", "SSH_AUTH_SOCK": "/agent"}


async def _reply(arguments: dict[str, object]) -> str:
    return "ok"


TOOL = AgentTool("brief", "Today so far.", {"type": "object", "properties": {}}, _reply)


def _adapter(tmp_path: Path) -> TmuxAdapter:
    server = TmuxServer(socket="unused", state_dir=tmp_path, binary="/usr/bin/tmux")
    return TmuxAdapter(
        server=server, kinds=default_kinds, clock=FakeClock(), environ=ENVIRON, python="py"
    )


def _argv(kind: str, request: RunRequest, tmp_path: Path) -> list[str]:
    return _adapter(tmp_path)._argv(default_kinds.get(kind), request, tmp_path)


def _worker(**overrides: object) -> RunRequest:
    return RunRequest(prompt="Fix it", cwd=Path("/w"), run_id=7, agent_tools=[TOOL], **overrides)  # type: ignore[arg-type]


def test_claude_code_starts_the_run_agents_tools_and_keeps_its_own(tmp_path: Path) -> None:
    argv = _argv("claude-code", _worker(), tmp_path)

    assert argv[argv.index("--mcp-config") + 1] == str(tmp_path / MCP_CONFIG_FILE)
    assert "--strict-mcp-config" in argv
    assert "--tools" not in argv
    config = json.loads((tmp_path / MCP_CONFIG_FILE).read_text(encoding="utf-8"))
    assert config["mcpServers"] == {
        "labhq-agent": {
            "type": "stdio",
            "command": "py",
            "args": ["-m", "labhq", "mcp", "agent", "--run", "7"],
            # labhq's settings only; the session's allowlist never carries them.
            "env": {"LABHQ_DATA_DIR": "/data"},
        }
    }


def test_codex_takes_the_server_as_config_overrides(tmp_path: Path) -> None:
    argv = _argv("codex", _worker(), tmp_path)

    overrides = [argv[i + 1] for i, word in enumerate(argv) if word == "-c"]
    assert (
        'mcp_servers.labhq-agent={command = "py", args = ["-m", "labhq", "mcp", "agent", '
        '"--run", "7"], env = {LABHQ_DATA_DIR = "/data"}}'
    ) in overrides


@pytest.mark.parametrize("kind", ["gemini", "aider"])
def test_a_cli_without_stdio_servers_runs_without_the_engine_tools(
    kind: str, tmp_path: Path
) -> None:
    argv = _argv(kind, _worker(), tmp_path)

    assert not any("mcp" in word for word in argv)


def test_own_tools_drop_every_built_in_tool_of_claude_code(tmp_path: Path) -> None:
    request = _worker(tools=[TOOL], tools_server=("mcp", "internal", "--call", "3"))
    argv = _argv("claude-code", request, tmp_path)

    assert argv[argv.index("--tools") + 1] == ""
    config = json.loads((tmp_path / MCP_CONFIG_FILE).read_text(encoding="utf-8"))
    own = config["mcpServers"]["labhq"]
    assert own["args"] == ["-m", "labhq", "mcp", "internal", "--call", "3"]
    assert set(config["mcpServers"]) == {"labhq", "labhq-agent"}


@pytest.mark.parametrize("kind", ["codex", "gemini", "aider"])
def test_a_cli_that_cannot_drop_its_tools_never_runs_with_own_tools(
    kind: str, tmp_path: Path
) -> None:
    request = _worker(tools=[TOOL], tools_server=("mcp", "internal", "--call", "3"))

    with pytest.raises(AdapterError, match="cannot drop its built-in shell and file tools"):
        _argv(kind, request, tmp_path)


def test_own_tools_need_a_server_to_serve_them(tmp_path: Path) -> None:
    with pytest.raises(AdapterError, match="no stdio server"):
        _argv("claude-code", _worker(tools=[TOOL]), tmp_path)


def test_every_tool_launch_records_its_source() -> None:
    for launch in TOOL_LAUNCHES.values():
        assert "checked 2026-10-03" in launch.source
    assert TOOL_LAUNCHES["claude_mcp"].exclusive == ("--tools", "")
    assert TOOL_LAUNCHES["codex_mcp"].exclusive is None


def test_claude_codes_reply_is_its_stop_hooks_last_message(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    kind = default_kinds.get("claude-code")
    signal = json.dumps({"session_id": "s", "last_assistant_message": "The build is green."})

    assert adapter._reply(kind, signal) == "The build is green."
    assert adapter._reply(kind, "not json") is None
    assert adapter._reply(default_kinds.get("codex"), signal) is None


def test_a_kind_naming_an_unknown_tool_launch_is_refused() -> None:
    kinds = default_kinds.copy()
    kind = replace(default_kinds.get("gemini"), name="other", tool_launch="nope")

    with pytest.raises(ValueError, match="unknown tool launch 'nope'"):
        kinds.register(kind)
