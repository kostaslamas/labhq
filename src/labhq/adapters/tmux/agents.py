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
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from labhq.adapters.tmux.blocking import BlockingScreen
from labhq.adapters.tmux.tomlvalue import toml_value
from labhq.adapters.tmux.tools import TOOL_LAUNCHES


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


class RulesInjection(StrEnum):
    """How a manager's rules reach an adopted agent (ADR 0005)."""

    # Words of `rules_words` on every start: survives compaction and new sessions.
    SYSTEM_PROMPT = "system_prompt"
    # A message after the move, sent again after every compaction or new session.
    FIRST_MESSAGE = "first_message"
    BOTH = "both"


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
    # Adoption (ADR 0005). `continue_` (a keyword otherwise) continues the most recent
    # conversation in the working directory; None means the agent cannot be adopted.
    continue_: tuple[str, ...] | None = None
    # Continue a conversation chosen by its exact id, instead of the latest one.
    continue_selected: tuple[str, ...] | None = None
    rules_injection: RulesInjection = RulesInjection.FIRST_MESSAGE
    # Added after the program name of `continue_` when the rules go in the system prompt;
    # `{rules}` is the rules' text and `{rules_file}` the path of `.labhq/rules.md`.
    rules_words: tuple[str, ...] = ()
    # A screen line that shows the conversation was compacted, so first-message rules go again.
    compaction_pattern: str | None = None
    # Process names discovery matches against the first two words of a command line; empty
    # means the program of `start`.
    processes: tuple[str, ...] = ()
    continue_source: str = ""
    # What a person picks it by, in lists and forms; the name is for commands and config.
    display_name: str = ""
    # Dialogs the agent can stop on before or during a turn (see `blocking`).
    blocking_screens: tuple[BlockingScreen, ...] = ()
    # Names from `controlkeys.CONTROL_KEYS` the owner may send to this agent; a key the CLI
    # does not act on is not listed.
    control_keys: tuple[str, ...] = ()

    @property
    def process_names(self) -> tuple[str, ...]:
        return self.processes or (Path(self.start[0]).name,)


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


# Claude Code 2.1.288, checked in tmux: the options are not numbered, the cursor starts on
# "No, exit", Down moves it to "Yes, I trust this folder" and Enter confirms.
CLAUDE_BLOCKING_SCREENS = (
    BlockingScreen(
        name="trust-folder",
        pattern=r"Is this a project you created or one you trust\?.*Yes, I trust this folder",
        reason="Claude Code asks whether to trust the working directory",
        accept_option="Yes, I trust this folder",
    ),
    BlockingScreen(
        name="login",
        pattern=r"Select login method|Please run /login|Invalid API key",
        reason="Claude Code is not logged in",
    ),
)

CLAUDE_CODE = AgentKind(
    name="claude-code",
    display_name="Claude Code",
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
    # Esc stops the turn, Shift+Tab cycles normal, auto-accept and plan mode, Ctrl+C cancels.
    control_keys=("escape", "shift_tab", "ctrl_c"),
    blocking_screens=CLAUDE_BLOCKING_SCREENS,
    reply_key="last_assistant_message",
    continue_=(
        "claude",
        "--dangerously-skip-permissions",
        "--continue",
        "--system-prompt-snapshot",
        "off",
    ),
    continue_selected=(
        "claude",
        "--dangerously-skip-permissions",
        "--resume",
        "{session_id}",
        "--system-prompt-snapshot",
        "off",
    ),
    rules_injection=RulesInjection.SYSTEM_PROMPT,
    rules_words=("--append-system-prompt", "{rules}"),
    continue_source=(
        "https://code.claude.com/docs/en/cli-reference: `--continue` loads the most recent "
        "conversation in the current directory; `--append-system-prompt` appends to the "
        "default prompt; a resumed conversation reuses the prompt recorded on its first "
        "request until compaction, so `--system-prompt-snapshot off` makes the appended "
        "rules apply at once; checked 2026-10-03"
    ),
)

# Paths below are in openai/codex at main 86a54b05, checked 2026-10-03. The contract runs
# against tests/adapters/fake_codex.py; docs/checks/codex-adapter.md runs it for real.
CODEX_FLAGS = (
    # Codex's --yolo aliases bypassing approvals and the sandbox; labhq's worktree,
    # push URL and environment are the boundary instead (ADR 0003).
    "--yolo",
    # Same file: run the session-flag hooks of `codex_config` without persisted trust.
    "--dangerously-bypass-hook-trust",
    # codex-rs/tui/src/cli.rs: inline mode keeps the transcript in the pane's scrollback.
    "--no-alt-screen",
)

CODEX = AgentKind(
    name="codex",
    display_name="Codex",
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
    reply_key="last_assistant_message",
    tool_launch="codex_mcp",
    # Shift+Tab is left out: nothing checked says Codex binds it.
    control_keys=("escape", "ctrl_c"),
    source=(
        "openai/codex main 86a54b05: codex-rs/cli/src/main.rs, codex-rs/tui/src/cli.rs, "
        "codex-rs/utils/cli/src/{shared_options,config_override}.rs, "
        "codex-rs/config/src/hook_config.rs, codex-rs/hooks (Stop, PreToolUse, exit code 2), "
        "codex-rs/tui/src/status (/status); checked 2026-10-03"
    ),
    # The same interactive flags as `resume`, so its hooks (turn signal, push guard) run too.
    continue_=("codex", "resume", "--last", *CODEX_FLAGS),
    continue_selected=("codex", "resume", *CODEX_FLAGS, "--", "{session_id}"),
    # `-c developer_instructions` exists, but whether a resumed thread takes it is unverified.
    rules_injection=RulesInjection.FIRST_MESSAGE,
    compaction_pattern=r"multiple compactions",
    continue_source=(
        "openai/codex main: codex-rs/cli/src/main.rs (`codex resume --last` continues the "
        "most recent session, filtered to the current directory unless `--all`), "
        'codex-rs/core/src/compact.rs (the warning after a compaction: "Long threads and '
        'multiple compactions ..."); checked 2026-10-03'
    ),
)

GEMINI = AgentKind(
    name="gemini",
    display_name="Gemini CLI",
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
    control_keys=("escape", "ctrl_c"),
    # MCP servers come only from Gemini CLI's settings files, which labhq does not write.
    source=(
        "google-gemini/gemini-cli main: packages/cli/src/config/config.ts (--session-id, "
        "--resume, -i/--prompt-interactive, --approval-mode yolo), "
        "docs/cli/session-management.md; checked 2026-10-03"
    ),
    continue_=("gemini", "--approval-mode", "yolo", "--resume", "latest"),
    continue_selected=("gemini", "--approval-mode", "yolo", "--resume", "{session_id}"),
    # GEMINI_SYSTEM_MD replaces the whole system prompt; there is no append.
    rules_injection=RulesInjection.FIRST_MESSAGE,
    compaction_pattern=r"Chat history compressed from",
    continue_source=(
        "google-gemini/gemini-cli main: packages/cli/src/config/config.ts (`--resume latest`), "
        "docs/cli/session-management.md (sessions are per project directory), "
        'packages/cli/src/ui/components/messages/CompressionMessage.tsx ("Chat history '
        'compressed from N to M tokens."); checked 2026-10-03'
    ),
)

AIDER = AgentKind(
    name="aider",
    display_name="Aider",
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
    control_keys=("ctrl_c",),
    source=(
        "Aider-AI/aider main: aider/website/docs/config/options.md (--message, "
        "--restore-chat-history, --yes-always, --no-pretty, --no-fancy-input); checked 2026-10-03"
    ),
    continue_=(
        "aider",
        "--yes-always",
        "--no-pretty",
        "--no-fancy-input",
        "--restore-chat-history",
    ),
    continue_selected=(
        "aider",
        "--yes-always",
        "--no-pretty",
        "--no-fancy-input",
        "--restore-chat-history",
    ),
    # A read-only file goes with every request, so the rules survive like a system prompt.
    rules_injection=RulesInjection.SYSTEM_PROMPT,
    rules_words=("--read", "{rules_file}"),
    continue_source=(
        "Aider-AI/aider main: aider/website/docs/config/options.md (--restore-chat-history "
        "restores the chat of the working directory; --read adds a read-only file to every "
        "request); checked 2026-10-03"
    ),
)

default_kinds = AgentKinds()
for _kind in (CLAUDE_CODE, CODEX, GEMINI, AIDER):
    default_kinds.register(_kind)
