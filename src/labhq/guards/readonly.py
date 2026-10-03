"""Read-only mode: commands and tools an agent that touches machines may use (plan §2.2, §5).

The classifier allows a command only when every program it runs is on an allowlist kept as
data: a program maps to a rule over its arguments. Wrappers (`env`, `timeout`, `ssh`, `sh -c`)
are seen through with the push guard's parser, so the inner command is the one checked.
Anything the classifier does not know is denied.

The Claude adapter enforces the mode in two layers. A PreToolUse hook classifies every Bash
command, because Claude Code approves what it considers read-only without asking
`can_use_tool` (spikes/agent_sdk/RESULTS.md §3). `can_use_tool` denies every tool outside
the read-only list, `Write`, `Edit` and `NotebookEdit` among them.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

from claude_agent_sdk import (
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)
from claude_agent_sdk.types import CanUseTool, PermissionResult

from labhq.guards.commands import (
    NO_OPTIONS,
    WRAPPERS,
    Deny,
    Handler,
    Nested,
    Options,
    Step,
    Wrapped,
    is_dynamic,
    program_name,
    split_options,
    strip_prefix_words,
)
from labhq.guards.hook import MAX_DEPTH, Verdict
from labhq.guards.shell import UnparsableCommandError, parse

# `agents.config["permission_mode"] = "read_only"` puts an agent in this mode.
PERMISSION_MODE_KEY = "permission_mode"
READ_ONLY_MODE = "read_only"

BASH_TOOL = "Bash"
# Tools that only read. Everything else, `Write`, `Edit` and `NotebookEdit` included, is denied.
READ_ONLY_TOOLS = frozenset({BASH_TOOL, "Read", "Glob", "Grep"})

# A rule returns why the arguments are not read-only, or None when they are.
type Rule = Callable[[Sequence[str]], str | None]


def is_read_only(agent_config: Mapping[str, Any]) -> bool:
    return agent_config.get(PERMISSION_MODE_KEY) == READ_ONLY_MODE


def any_arguments(args: Sequence[str]) -> str | None:
    return None


def without(*prefixes: str) -> Rule:
    """Any arguments except words that start with one of `prefixes`."""

    def rule(args: Sequence[str]) -> str | None:
        found = next((word for word in args if word.startswith(prefixes)), None)
        return None if found is None else f"{found} changes state"

    return rule


def with_flags(required: Sequence[str] = (), denied: Sequence[str] = ()) -> Rule:
    def rule(args: Sequence[str]) -> str | None:
        missing = [flag for flag in required if flag not in args]
        if missing:
            return f"needs {' '.join(missing)}"
        return without(*denied)(args) if denied else None

    return rule


def only_options(allowed: Iterable[str], takes_value: Iterable[str] = ()) -> Rule:
    """Every option must be listed in `allowed`; operands are free."""
    allowed_set, valued = frozenset(allowed), frozenset(takes_value)

    def rule(args: Sequence[str]) -> str | None:
        skip = False
        for word in args:
            if skip:
                skip = False
                continue
            if not word.startswith("-") or word == "-":
                continue
            name = word.partition("=")[0]
            if name not in allowed_set:
                return f"option {name} is not on the read-only list"
            skip = name in valued and "=" not in word
        return None

    return rule


def subcommands(table: Mapping[str, Rule], options: Options = NO_OPTIONS) -> Rule:
    """The first operand after the global options names the subcommand; it must be listed."""

    def rule(args: Sequence[str]) -> str | None:
        _, operands = split_options(args, options)
        if not operands:
            return "no read-only subcommand"
        check = table.get(operands[0])
        if check is None:
            return f"{operands[0]} is not a read-only subcommand"
        return check(operands[1:])

    return rule


def _values(*names: str) -> frozenset[str]:
    return frozenset(names)


_SYSTEMCTL = subcommands(
    dict.fromkeys(
        (
            "status",
            "is-active",
            "is-failed",
            "is-enabled",
            "list-units",
            "list-timers",
            "list-unit-files",
            "show",
            "cat",
        ),
        any_arguments,
    ),
    Options(
        takes_value=_values(
            "-H", "--host", "-M", "--machine", "-t", "--type", "-p", "--property", "-n", "-o"
        )
    ),
)

_DOCKER = subcommands(
    {
        **dict.fromkeys(
            ("ps", "inspect", "logs", "images", "version", "info", "top"), any_arguments
        ),
        "stats": with_flags(required=("--no-stream",)),
    },
    Options(takes_value=_values("-H", "--host", "-c", "--context", "--config", "-l")),
)

# A new read-only program is a new row here, never a new branch in the classifier.
READ_ONLY_PROGRAMS: dict[str, Rule] = {
    **dict.fromkeys(
        (
            "df",
            "du",
            "free",
            "uptime",
            "ps",
            "cat",
            "head",
            "tail",
            "ls",
            "grep",
            "wc",
            "stat",
            "uname",
            "id",
            "whoami",
            "who",
            "w",
            "nproc",
            "lsblk",
            "echo",
        ),
        any_arguments,
    ),
    "ss": without("-K", "--kill"),
    "systemctl": _SYSTEMCTL,
    "journalctl": without(
        "--vacuum-",
        "--rotate",
        "--flush",
        "--sync",
        "--relinquish-var",
        "--smart-relinquish-var",
        "--setup-keys",
        "--update-catalog",
    ),
    "smartctl": only_options(
        ("-a", "-H", "-i", "-A", "-x", "-j", "-d", "--all", "--health", "--info", "--json"),
        takes_value=("-d",),
    ),
    "docker": _DOCKER,
    "openssl": subcommands(
        {"x509": with_flags(required=("-noout",), denied=("-out", "-CAcreateserial"))}
    ),
    "apt": subcommands(
        dict.fromkeys(("list", "show", "policy"), any_arguments),
        Options(takes_value=_values("-o", "-c", "-t")),
    ),
}

_ESCALATION = "privilege escalation is never read-only"
DENIED_PROGRAMS: dict[str, str] = dict.fromkeys(
    ("sudo", "doas", "su", "runuser", "pkexec"), _ESCALATION
)


def _ssh(args: Sequence[str], open_ended: bool) -> Iterator[Step]:
    # `-o ProxyCommand=...` and `-o LocalCommand=...` run a command on this machine.
    for index, word in enumerate(args):
        value = args[index + 1] if word == "-o" and index + 1 < len(args) else word
        if word.startswith("-o") and "command" in value.lower():
            yield Deny("ssh options that run a local command")
            return
    yield from WRAPPERS["ssh"](args, open_ended)


# Programs that run another command: the classifier checks that command instead.
READ_ONLY_WRAPPERS: dict[str, Handler] = {
    "env": WRAPPERS["env"],
    "timeout": WRAPPERS["timeout"],
    "nice": WRAPPERS["nice"],
    "ssh": _ssh,
    **{name: WRAPPERS[name] for name in ("sh", "bash", "dash", "zsh", "ksh", "ash")},
}

# Program paths outside these may be a repository's own script wearing a known name.
SYSTEM_DIRECTORIES = frozenset({"/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin"})
_DISCARD_TARGET = "/dev/null"


def classify(command: str) -> Verdict:
    """Decide whether a Bash command line only reads."""
    return Verdict(reasons=tuple(dict.fromkeys(_script_denials(command, 0))))


def _script_denials(script: str, depth: int) -> Iterator[str]:
    if depth > MAX_DEPTH:
        yield "command nests too deeply to analyse"
        return
    try:
        parsed = parse(script)
    except UnparsableCommandError as error:
        yield f"command cannot be parsed ({error})"
        return
    for operator, target in parsed.redirections:
        if _writes(operator, target):
            yield f"output redirection {operator} {target}".rstrip()
    # Here-document bodies are input; the program reading them is checked as a command.
    for nested in parsed.nested:
        yield from _script_denials(nested, depth + 1)
    for words in parsed.commands:
        yield from _command_denials(words, depth)


def _writes(operator: str, target: str) -> bool:
    if ">" not in operator:
        return False
    if "(" in operator or operator == "<>":
        return True
    # `2>/dev/null` and `2>&1` discard or merge output; they write nothing.
    return not (target == _DISCARD_TARGET or (operator.endswith("&") and target.isdigit()))


def _command_denials(words: Sequence[str], depth: int) -> Iterator[str]:
    if depth > MAX_DEPTH:
        yield "command nests too deeply to analyse"
        return
    command = strip_prefix_words(words)
    if not command:
        return
    word = command[0]
    if is_dynamic(word):
        yield f"program name {word!r} is computed at run time"
        return
    if "/" in word and str(PurePosixPath(word).parent) not in SYSTEM_DIRECTORIES:
        yield f"{word} is not a system program"
        return
    name, args = program_name(word), command[1:]
    if name in DENIED_PROGRAMS:
        yield f"{name}: {DENIED_PROGRAMS[name]}"
    elif name in READ_ONLY_WRAPPERS:
        yield from _wrapper_denials(name, READ_ONLY_WRAPPERS[name](args, False), depth)
    elif name in READ_ONLY_PROGRAMS:
        reason = READ_ONLY_PROGRAMS[name](args)
        if reason is not None:
            yield f"{name}: {reason}"
    else:
        yield f"{name} is not a known read-only program"


def _wrapper_denials(name: str, steps: Iterator[Step], depth: int) -> Iterator[str]:
    ran = False
    for step in steps:
        ran = True
        match step:
            case Deny(reason):
                yield f"{name}: {reason}"
            case Nested(script):
                yield from _script_denials(script, depth + 1)
            case Wrapped(words):
                yield from _command_denials(words, depth + 1)
    if not ran:
        # `bash script.sh`, a bare `ssh host` or `env`: what runs is not on the line.
        yield f"{name} runs nothing the classifier can check"


def _deny(reason: str) -> HookJSONOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"This agent runs read-only commands only: {reason}.",
        }
    }


async def deny_writes(
    input_data: HookInput, tool_use_id: str | None, context: HookContext
) -> HookJSONOutput:
    if input_data["hook_event_name"] != "PreToolUse" or input_data["tool_name"] != BASH_TOOL:
        return {}
    command = input_data["tool_input"].get("command")
    if not isinstance(command, str):
        return _deny("the Bash call carries no command string")
    verdict = classify(command)
    return {} if verdict.allowed else _deny("; ".join(verdict.reasons))


def read_only_matcher() -> HookMatcher:
    """The `PreToolUse` matcher the Claude adapter adds to every read-only run."""
    return HookMatcher(matcher=BASH_TOOL, hooks=[deny_writes])


def read_only_permissions(extra_tools: Iterable[str] = ()) -> CanUseTool:
    """A `can_use_tool` callback that allows the read-only tools and `extra_tools` only."""
    allowed = READ_ONLY_TOOLS | frozenset(extra_tools)

    async def can_use_tool(
        tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResult:
        if tool_name not in allowed:
            return PermissionResultDeny(message=f"{tool_name} is not available in read-only mode.")
        if tool_name != BASH_TOOL:
            return PermissionResultAllow()
        command = tool_input.get("command")
        verdict = classify(command) if isinstance(command, str) else Verdict(("no command",))
        if verdict.allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(
            message="Read-only commands only: " + "; ".join(verdict.reasons)
        )

    return can_use_tool
