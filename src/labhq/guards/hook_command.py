"""The push guard as a command: `python -m labhq.guards.hook_command` (ADR 0003).

Agents that run external hook commands (Claude Code's `PreToolUse`) pipe the hook payload
on stdin. A shell command that publishes is denied with exit code 2 and the reason on
stderr, which blocks the tool call; anything else exits 0 with no output. A payload the
guard cannot read is denied: a guard that fails open is no guard.
"""

import json
import sys
from typing import Any, TextIO

from labhq.guards.hook import check_command

DENY_EXIT_CODE = 2
# Tool name -> the key of its input that holds the shell command, per agent.
SHELL_TOOLS: dict[str, str] = {"Bash": "command", "run_shell_command": "command"}


def denial(payload: Any) -> str | None:
    """The reason to deny the tool call in `payload`, or None to let it run."""
    if not isinstance(payload, dict):
        return "the hook payload is not a JSON object"
    key = SHELL_TOOLS.get(str(payload.get("tool_name")))
    if key is None:
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get(key) if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return "the shell call carries no command string"
    verdict = check_command(command)
    return None if verdict.allowed else "; ".join(verdict.reasons)


def run(stdin: TextIO, stderr: TextIO) -> int:
    try:
        payload = json.loads(stdin.read())
    except ValueError:
        payload = None
    reason = denial(payload)
    if reason is None:
        return 0
    print(f"Publishing is reserved to the engine after an approval: {reason}.", file=stderr)
    return DENY_EXIT_CODE


def main() -> int:
    return run(sys.stdin, sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
