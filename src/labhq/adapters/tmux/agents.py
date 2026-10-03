"""Supported CLI agents, one registry entry each (ADR 0003, "Agents are data").

A template is a tuple of words; `{prompt}`, `{session_id}` and `{guard_hook}` are filled
in per run, and the words of the agent's launch integration (statusline, turn signal, push
guard hook) go right after the program name. Adding an agent is one `register` call.

Every entry records where its commands and flags were checked. The screens they print are
tested through fixtures, and the whole path through a developer machine is the manual check
in docs/checks/tmux-adapter.md.
"""

import json
import shlex
import sys
from collections.abc import Callable
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


def codex_notify(context: LaunchContext) -> list[str]:
    # Codex appends the turn's JSON payload as the last argument of the notify program.
    program = signal_command(context, "turn", context.signal_path)
    return ["-c", f"notify={json.dumps(program)}"]


LAUNCHES: dict[str, Launch] = {"claude_settings": claude_settings, "codex_notify": codex_notify}


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
        "--dangerously-skip-permissions), /hooks (Stop, PreToolUse, exit code 2), "
        "/statusline (rate_limits, cost.total_cost_usd); checked 2026-10-03"
    ),
)

CODEX = AgentKind(
    name="codex",
    start=("codex", "--dangerously-bypass-approvals-and-sandbox", "{prompt}"),
    resume=(
        "codex",
        "resume",
        "--dangerously-bypass-approvals-and-sandbox",
        "{session_id}",
        "{prompt}",
    ),
    session_id=SessionIdSource.SIGNAL,
    session_key="thread-id",
    interrupt_keys=("Escape",),
    turn_end=TurnEnd.SIGNAL,
    usage_source=UsageSource.SCREEN,
    launch="codex_notify",
    hooks=None,
    usage_command="/status",
    source=(
        "openai/codex main: codex-rs/cli/src/main.rs (`codex [OPTIONS] [PROMPT]`, "
        "`codex resume <SESSION_ID>`), codex-rs/utils/cli/src/config_override.rs (`-c key=value`), "
        "codex-rs/core config `notify` (agent-turn-complete payload with `thread-id`); "
        "checked 2026-10-03"
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
