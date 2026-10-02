"""The PreToolUse hook that keeps workers from publishing (plan §5, rule 5).

The hook is one of three layers. The worktree's push URL points nowhere and the worker's
environment holds no git credentials (`labhq.worktrees`), so a command the parser cannot
see through still fails at the transport. Hooks are honoured under `bypassPermissions`
(spikes/agent_sdk/RESULTS.md §1).
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from claude_agent_sdk import HookContext, HookInput, HookJSONOutput, HookMatcher

from labhq.guards.commands import (
    WRAPPERS,
    Deny,
    Handler,
    Nested,
    Step,
    Wrapped,
    is_dynamic,
    program_name,
    strip_prefix_words,
)
from labhq.guards.rules import DASH_FORMS, PROGRAMS
from labhq.guards.shell import UnparsableCommandError, parse

GUARDED_TOOL = "Bash"
# Deeper nesting than this is not something an honest command needs.
MAX_DEPTH = 8

HANDLERS: dict[str, Handler] = {**WRAPPERS, **PROGRAMS}


@dataclass(frozen=True)
class Verdict:
    reasons: tuple[str, ...]

    @property
    def allowed(self) -> bool:
        return not self.reasons


def check_command(command: str) -> Verdict:
    """Decide whether a Bash command line may run in a worker."""
    return Verdict(reasons=tuple(dict.fromkeys(_script_denials(command, 0, lenient=False))))


def _script_denials(script: str, depth: int, *, lenient: bool) -> Iterator[str]:
    if depth > MAX_DEPTH:
        yield "command nests too deeply to analyse"
        return
    try:
        parsed = parse(script, lenient=lenient)
    except UnparsableCommandError as error:
        yield f"command cannot be parsed ({error})"
        return
    for nested in parsed.nested:
        yield from _script_denials(nested, depth + 1, lenient=False)
    for document in parsed.documents:
        yield from _script_denials(document, depth + 1, lenient=True)
    for words in parsed.commands:
        yield from _command_denials(words, depth, open_ended=False)


def _command_denials(words: Sequence[str], depth: int, *, open_ended: bool) -> Iterator[str]:
    if depth > MAX_DEPTH:
        yield "command nests too deeply to analyse"
        return
    command = strip_prefix_words(words)
    if not command:
        return
    if is_dynamic(command[0]):
        yield f"program name {command[0]!r} is computed at run time"
        return
    handler, args = _resolve(program_name(command[0]), command[1:])
    if handler is None:
        return
    for step in handler(args, open_ended):
        yield from _step_denials(step, depth)


def _resolve(name: str, args: Sequence[str]) -> tuple[Handler | None, Sequence[str]]:
    if name in HANDLERS:
        return HANDLERS[name], args
    for prefix, program in DASH_FORMS.items():
        if name.startswith(prefix):
            return HANDLERS[program], [name.removeprefix(prefix), *args]
    return None, args


def _step_denials(step: Step, depth: int) -> Iterator[str]:
    match step:
        case Deny(reason):
            yield reason
        case Nested(script):
            yield from _script_denials(script, depth + 1, lenient=False)
        case Wrapped(words, open_ended):
            yield from _command_denials(words, depth + 1, open_ended=open_ended)


def _deny(reason: str) -> HookJSONOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Publishing is reserved to the engine after an approval: {reason}."
            ),
        }
    }


async def deny_publishing(
    input_data: HookInput, tool_use_id: str | None, context: HookContext
) -> HookJSONOutput:
    if input_data["hook_event_name"] != "PreToolUse" or input_data["tool_name"] != GUARDED_TOOL:
        return {}
    command = input_data["tool_input"].get("command")
    if not isinstance(command, str):
        return _deny("the Bash call carries no command string")
    verdict = check_command(command)
    if verdict.allowed:
        return {}
    return _deny("; ".join(verdict.reasons))


def push_guard_matcher() -> HookMatcher:
    """The `PreToolUse` matcher the Claude adapter registers for every worker run."""
    return HookMatcher(matcher=GUARDED_TOOL, hooks=[deny_publishing])
