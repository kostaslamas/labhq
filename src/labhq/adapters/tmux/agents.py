"""Supported CLI agents, one registry entry each (ADR 0003, "Agents are data").

A template is a tuple of words; `{prompt}`, `{session_id}` and `{guard_hook}` are filled
in per run, and the words of the agent's launch integration (statusline, turn signal, push
guard hook) and of its tool servers go right after the program name. Adding an agent is one
`register` call.

Every entry records where its commands and flags were checked. The screens they print are
tested through fixtures, and the whole path through a developer machine is the manual check
in docs/checks/tmux-adapter.md.
"""

import json
import os
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SessionIdSource(StrEnum):
    # labhq picks a UUID and passes it at start, so it never has to be discovered.
    ASSIGNED = "assigned"
    # Read from the payload of the agent's turn-end signal, under `session_key`.
    SIGNAL = "signal"
    # The agent keeps one conversation per working directory; `session_key` names it.
    FIXED = "fixed"


class TurnEnd(StrEnum):
    # The agent runs a command labhq gave it when a turn completes.
    SIGNAL = "signal"
    # The agent exits after one turn.
    EXIT = "exit"
    # The screen matches `turn_end_pattern`.
    PATTERN = "pattern"
    # The screen has not changed for `quiescence_seconds`.
    QUIESCENCE = "quiescence"


class UsageSource(StrEnum):
    # The Claude Code statusline JSON; no model call.
    STATUSLINE = "statusline"
    # The pane, read by the extractor after `usage_command`.
    SCREEN = "screen"


@dataclass(frozen=True)
class LaunchContext:
    """Paths and commands a launch integration may hand to the agent."""

    python: str
    signal_path: Path
    statusline_path: Path
    guard_hook: str


Launch = Callable[[LaunchContext], list[str]]


@dataclass(frozen=True)
class AgentKind:
    name: str
    start: tuple[str, ...]
    resume: tuple[str, ...] | None
    session_id: SessionIdSource
    interrupt_keys: tuple[str, ...]
    turn_end: TurnEnd
    usage_source: UsageSource
    # Key of the launch integration in `LAUNCHES`, or None for none.
    launch: str | None
    # The guard hook is installed through the launch integration; None means the agent can
    # run no external hook command, so it relies on the push URL and the environment.
    hooks: str | None
    usage_command: str | None
    source: str
    session_key: str | None = None
    turn_end_pattern: str | None = None
    # A screen line that is the agent's own output (a reply or a tool call); each new one is
    # reported as an `assistant` event. None: the agent's lines cannot be told apart.
    reply_pattern: str | None = None
    # Key of the stdio MCP integration in `TOOL_LAUNCHES`, or None for a CLI that takes none.
    tool_launch: str | None = None
    # Key of the turn-end signal's payload that carries the turn's final reply, if any.
    reply_key: str | None = None


def signal_command(context: LaunchContext, channel: str, path: Path) -> list[str]:
    return [context.python, "-m", "labhq.adapters.tmux.signal", channel, str(path)]


def _shell(words: list[str]) -> str:
    return " ".join(shlex.quote(word) for word in words)


def claude_settings(context: LaunchContext) -> list[str]:
    """Settings passed with `--settings`; the owner's settings files are never edited."""
    settings = {
        "statusLine": {
            "type": "command",
            "command": _shell(signal_command(context, "statusline", context.statusline_path)),
        },
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": _shell(signal_command(context, "turn", context.signal_path)),
                        }
                    ]
                }
            ],
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": context.guard_hook}]}
            ],
        },
    }
    return ["--settings", json.dumps(settings)]


def toml_value(value: object) -> str:
    """A TOML inline value, as Codex parses the right side of `-c key=value`."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # A JSON string without ASCII escapes is a TOML basic string.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = (f"{key} = {toml_value(item)}" for key, item in value.items())
        return "{" + ", ".join(pairs) + "}"
    raise TypeError(f"no TOML form for {type(value).__name__}")


def _codex_hook(command: str, matcher: str | None = None) -> list[dict[str, object]]:
    group: dict[str, object] = {"hooks": [{"type": "command", "command": command}]}
    return [{"matcher": matcher, **group}] if matcher is not None else [group]


def codex_config(context: LaunchContext) -> list[str]:
    """Session-only `-c` overrides; the owner's `~/.codex/config.toml` is never edited.

    openai/codex main (86a54b05): codex-rs/utils/cli/src/config_override.rs parses each value
    as TOML and applies dotted keys; codex-rs/config/src/hook_config.rs reads `hooks.<Event>`
    matcher groups from any config layer, the session flags included; codex-rs/hooks/src/
    events/stop.rs and pre_tool_use.rs run command hooks with the payload on stdin, and exit
    code 2 with a reason on stderr blocks the tool call. Hooks from session flags are
    untrusted unless `--dangerously-bypass-hook-trust` is given, so the templates pass it.
    """
    turn = _shell(signal_command(context, "turn", context.signal_path))
    overrides: dict[str, object] = {
        # Stable and on by default (codex-rs/features/src/lib.rs); pinned against a config
        # that turns it off, since the turn signal depends on it.
        "features.hooks": True,
        # An update prompt at start would block the first turn.
        "check_for_update_on_startup": False,
        # The run's cwd is labhq's worktree; never stop on "resume in which directory?".
        "tui.resume_cwd": "current",
        # Stop replaces the legacy `notify`, which codex-rs/hooks/src/legacy_notify.rs marks
        # for removal; its payload carries `session_id`, the id `codex resume` takes.
        "hooks.Stop": _codex_hook(turn),
        "hooks.PreToolUse": _codex_hook(context.guard_hook, matcher="Bash"),
    }
    return [
        word for key, value in overrides.items() for word in ("-c", f"{key}={toml_value(value)}")
    ]


LAUNCHES: dict[str, Launch] = {"claude_settings": claude_settings, "codex_config": codex_config}


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


class UnknownAgentKindError(LookupError):
    pass


class AgentKinds:
    def __init__(self) -> None:
        self._kinds: dict[str, AgentKind] = {}

    def register(self, kind: AgentKind, *, replace: bool = False) -> None:
        if kind.name in self._kinds and not replace:
            raise ValueError(f"agent kind {kind.name!r} is already registered")
        if kind.launch is not None and kind.launch not in LAUNCHES:
            raise ValueError(f"agent kind {kind.name!r} names an unknown launch {kind.launch!r}")
        if kind.tool_launch is not None and kind.tool_launch not in TOOL_LAUNCHES:
            raise ValueError(
                f"agent kind {kind.name!r} names an unknown tool launch {kind.tool_launch!r}"
            )
        self._kinds[kind.name] = kind

    def get(self, name: str) -> AgentKind:
        try:
            return self._kinds[name]
        except KeyError:
            raise UnknownAgentKindError(f"no tmux agent kind {name!r}") from None

    def names(self) -> list[str]:
        return sorted(self._kinds)

    def copy(self) -> "AgentKinds":
        clone = AgentKinds()
        clone._kinds = dict(self._kinds)
        return clone


def default_python() -> str:
    return sys.executable


CLAUDE_CODE = AgentKind(
    name="claude-code",
    start=("claude", "--dangerously-skip-permissions", "--session-id", "{session_id}", "{prompt}"),
    resume=("claude", "--dangerously-skip-permissions", "--resume", "{session_id}", "{prompt}"),
    session_id=SessionIdSource.ASSIGNED,
    interrupt_keys=("Escape",),
    turn_end=TurnEnd.SIGNAL,
    usage_source=UsageSource.STATUSLINE,
    launch="claude_settings",
    hooks="PreToolUse command hook in --settings",
    usage_command=None,
    source=(
        "https://code.claude.com/docs/en/cli-reference (--session-id, --resume, --settings, "
        "--dangerously-skip-permissions), /hooks (Stop, PreToolUse, exit code 2, "
        "Stop's last_assistant_message), /statusline (rate_limits, cost.total_cost_usd); "
        "checked 2026-10-03"
    ),
    tool_launch="claude_mcp",
    reply_key="last_assistant_message",
)

# Paths below are in openai/codex at main 86a54b05, checked 2026-10-03. The contract runs
# against tests/adapters/fake_codex.py; docs/checks/codex-adapter.md runs it for real.
CODEX_FLAGS = (
    # codex-rs/utils/cli/src/shared_options.rs: no approvals, no sandbox; labhq's worktree,
    # push URL and environment are the boundary instead (ADR 0003).
    "--dangerously-bypass-approvals-and-sandbox",
    # Same file: run the session-flag hooks of `codex_config` without persisted trust.
    "--dangerously-bypass-hook-trust",
    # codex-rs/tui/src/cli.rs: inline mode keeps the transcript in the pane's scrollback.
    "--no-alt-screen",
)

CODEX = AgentKind(
    name="codex",
    # codex-rs/tui/src/cli.rs: `codex [OPTIONS] [PROMPT]`; `--` keeps a prompt that starts
    # with a dash a prompt.
    start=("codex", *CODEX_FLAGS, "--", "{prompt}"),
    # codex-rs/cli/src/main.rs `ResumeCommand`: `codex resume [OPTIONS] [SESSION_ID]
    # [PROMPT]`, taking every interactive flag; root `-c` overrides are prepended to it.
    resume=("codex", "resume", *CODEX_FLAGS, "--", "{session_id}", "{prompt}"),
    # codex-rs/hooks/schema/generated/stop.command.input.schema.json: `session_id`, the
    # thread id that `codex resume` takes; Codex assigns it, so it is read from the signal.
    session_id=SessionIdSource.SIGNAL,
    session_key="session_id",
    # codex-rs/tui chatwidget snapshots: "• Working (0s • esc to interrupt)".
    interrupt_keys=("Escape",),
    # The `Stop` hook in `codex_config` runs the turn signal when a turn completes.
    turn_end=TurnEnd.SIGNAL,
    # codex-rs/tui/src/status/snapshots: `/status` prints the 5h, weekly or monthly limit as
    # "N% left"; no structured source reaches labhq, so the extractor reads the screen.
    usage_source=UsageSource.SCREEN,
    usage_command="/status",
    launch="codex_config",
    # codex-rs/core/src/tools/hook_names.rs: shell calls reach `PreToolUse` as tool `Bash`
    # with `{"command": ...}`, the payload `labhq.guards.hook_command` reads.
    hooks="PreToolUse command hook in -c hooks.PreToolUse",
    # codex-rs/tui chatwidget snapshots: replies and tool calls start with "• "; the
    # "• Working (Ns • esc to interrupt)" status line redraws every second and is not one.
    reply_pattern=r"^• (?!Working \()",
    tool_launch="codex_mcp",
    source=(
        "openai/codex main 86a54b05: codex-rs/cli/src/main.rs, codex-rs/tui/src/cli.rs, "
        "codex-rs/utils/cli/src/{shared_options,config_override}.rs, "
        "codex-rs/config/src/hook_config.rs, codex-rs/hooks (Stop, PreToolUse, exit code 2), "
        "codex-rs/tui/src/status (/status); checked 2026-10-03"
    ),
)

GEMINI = AgentKind(
    name="gemini",
    start=("gemini", "--approval-mode", "yolo", "--session-id", "{session_id}", "-i", "{prompt}"),
    resume=("gemini", "--approval-mode", "yolo", "--resume", "{session_id}", "-i", "{prompt}"),
    session_id=SessionIdSource.ASSIGNED,
    interrupt_keys=("Escape",),
    # Gemini CLI hooks live only in settings files, which labhq does not write.
    turn_end=TurnEnd.QUIESCENCE,
    usage_source=UsageSource.SCREEN,
    launch=None,
    hooks=None,
    usage_command="/stats",
    # MCP servers come only from Gemini CLI's settings files, which labhq does not write.
    source=(
        "google-gemini/gemini-cli main: packages/cli/src/config/config.ts (--session-id, "
        "--resume, -i/--prompt-interactive, --approval-mode yolo), "
        "docs/cli/session-management.md; checked 2026-10-03"
    ),
)

AIDER = AgentKind(
    name="aider",
    start=("aider", "--yes-always", "--no-pretty", "--no-fancy-input", "--message", "{prompt}"),
    resume=(
        "aider",
        "--yes-always",
        "--no-pretty",
        "--no-fancy-input",
        "--restore-chat-history",
        "--message",
        "{prompt}",
    ),
    # The chat history file lives in the working directory; resume restores it.
    session_id=SessionIdSource.FIXED,
    session_key=".aider.chat.history.md",
    interrupt_keys=("C-c",),
    turn_end=TurnEnd.EXIT,
    usage_source=UsageSource.SCREEN,
    launch=None,
    hooks=None,
    # `--message` exits after the reply, whose screen already carries the token and cost line.
    usage_command=None,
    source=(
        "Aider-AI/aider main: aider/website/docs/config/options.md (--message, "
        "--restore-chat-history, --yes-always, --no-pretty, --no-fancy-input); checked 2026-10-03"
    ),
)

default_kinds = AgentKinds()
for _kind in (CLAUDE_CODE, CODEX, GEMINI, AIDER):
    default_kinds.register(_kind)
