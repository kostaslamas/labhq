"""How an agent's CLI starts labhq's stdio tool servers, one integration per CLI.

An agent kind names its integration by key in `TOOL_LAUNCHES`, and each records where its
flags were checked. The adapter decides which servers a run gets; an integration only says
how its CLI takes them, and how (if at all) it drops the CLI's built-in tools.
"""

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from labhq.adapters.tmux.tomlvalue import toml_value


@dataclass(frozen=True)
class ToolServer:
    """A stdio MCP server the agent's CLI starts as its child: a `labhq mcp` command."""

    name: str
    argv: tuple[str, ...]
    # labhq's own settings (`LABHQ_*`), which the session's environment does not carry.
    env: Mapping[str, str]


# Words that make the CLI start `servers` as children; the path is the run's own directory.
ToolAttach = Callable[[Path, Sequence[ToolServer]], list[str]]


@dataclass(frozen=True)
class ToolLaunch:
    attach: ToolAttach
    # Words that take every built-in tool away (shell, file reads and writes), leaving only
    # the attached servers' tools. None: the CLI cannot drop them, so it never runs an agent
    # that must have only its own tools, such as the Call Center (ADR 0004).
    exclusive: tuple[str, ...] | None
    source: str


MCP_CONFIG_FILE = "mcp.json"


def claude_mcp(run_dir: Path, servers: Sequence[ToolServer]) -> list[str]:
    # A file, not an inline JSON argument: the servers' environment stays out of `ps`.
    config = {
        "mcpServers": {
            server.name: {
                "type": "stdio",
                "command": server.argv[0],
                "args": list(server.argv[1:]),
                "env": dict(server.env),
            }
            for server in servers
        }
    }
    path = run_dir / MCP_CONFIG_FILE
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as file:
        file.write(json.dumps(config))
    # Only these servers: the owner's own MCP configuration stays out of labhq's runs.
    return ["--mcp-config", str(path), "--strict-mcp-config"]


def codex_mcp(run_dir: Path, servers: Sequence[ToolServer]) -> list[str]:
    words: list[str] = []
    for server in servers:
        table = {"command": server.argv[0], "args": list(server.argv[1:]), "env": dict(server.env)}
        words += ["-c", f"mcp_servers.{server.name}={toml_value(table)}"]
    return words


TOOL_LAUNCHES: dict[str, ToolLaunch] = {
    "claude_mcp": ToolLaunch(
        attach=claude_mcp,
        exclusive=("--tools", ""),
        source=(
            "https://code.claude.com/docs/en/cli-reference (--mcp-config takes files, "
            '--strict-mcp-config, --tools "" disables every built-in tool and leaves MCP '
            "tools); claude-agent-sdk 0.2.163 subprocess_cli.py passes `tools=[]` the same "
            "way; checked 2026-10-03"
        ),
    ),
    "codex_mcp": ToolLaunch(
        attach=codex_mcp,
        # `features.shell_tool` turns the shell off, but no documented switch removes
        # apply_patch, so Codex never runs an agent that must have no file-writing tool.
        exclusive=None,
        source=(
            "openai/codex main: codex-rs/config/src/mcp_types.rs (mcp_servers.<name>.command, "
            "args, env), codex-rs/features/src/lib.rs (shell_tool); checked 2026-10-03"
        ),
    ),
}
