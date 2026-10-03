"""The `rtk` PreToolUse hook: worker shell commands run through `rtk`, which filters their
output (tests, builds, logs) before it reaches the model (plan §7.1).

`rtk rewrite <command>` decides which commands it has a filter for and prints the rewritten
command; anything else runs unchanged. Without the binary the hook is off and the run gets a
visible warning instead of a silent loss of the saving.
"""

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (
    HookCallback,
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
)

logger = logging.getLogger(__name__)

RTK_BINARY = "rtk"
SHELL_TOOL = "Bash"
RTK_MISSING = "rtk_missing"
REWRITE_TIMEOUT_SECONDS = 5.0
# `rtk rewrite` prints the rewritten command and exits 0 when its rules allow it, or 3 when no
# rule matched and the host should keep its own prompt; 3 is the common case. It exits 1 with
# no filter and 2 on a deny rule. This hook never grants permission, so 0 and 3 are both just a
# rewrite (rtk 0.51.0, src/hooks/rewrite_cmd.rs).
REWRITTEN_EXIT_CODES = frozenset({0, 3})
# rtk reads its own config from the home directory; nothing else reaches the child process.
_CHILD_ENV_KEYS = ("PATH", "HOME")


@dataclass(frozen=True, slots=True)
class RunWarning:
    """A warning the run records in `run_events` so the owner sees it."""

    code: str
    message: str

    def as_event_payload(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class RtkHook:
    """The hook matchers for the Claude adapter, plus any warning for the run."""

    binary: Path | None
    matchers: list[HookMatcher] = field(default_factory=list)
    warnings: tuple[RunWarning, ...] = ()

    @property
    def enabled(self) -> bool:
        return self.binary is not None

    def hooks(self) -> dict[str, list[HookMatcher]]:
        """Shaped for `ClaudeAgentOptions.hooks`; empty when the hook is off."""
        return {"PreToolUse": list(self.matchers)} if self.matchers else {}


def _child_env() -> dict[str, str]:
    return {key: os.environ[key] for key in _CHILD_ENV_KEYS if key in os.environ}


async def rewrite_command(
    binary: Path, command: str, timeout: float = REWRITE_TIMEOUT_SECONDS
) -> str | None:
    """The command `rtk` would run instead, or None when it has no filter for it."""
    try:
        process = await asyncio.create_subprocess_exec(
            str(binary),
            "rewrite",
            command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=_child_env(),
        )
    except OSError:
        logger.warning("rtk could not start; running the command unfiltered", exc_info=True)
        return None
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        logger.warning("rtk rewrite timed out; running the command unfiltered")
        return None
    rewritten = stdout.decode("utf-8", errors="replace").strip()
    if process.returncode not in REWRITTEN_EXIT_CODES or not rewritten or rewritten == command:
        return None
    return rewritten


def make_rewrite_hook(binary: Path) -> HookCallback:
    async def rtk_rewrite(
        hook_input: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if hook_input["hook_event_name"] != "PreToolUse" or hook_input["tool_name"] != SHELL_TOOL:
            return {}
        command = hook_input["tool_input"].get("command")
        if not isinstance(command, str) or not command.strip():
            return {}
        rewritten = await rewrite_command(binary, command)
        if rewritten is None:
            return {}
        # No permissionDecision: this hook only rewrites. An "allow" here would bypass the
        # approval gate, and the push guard's deny must stay the deciding answer.
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": {**hook_input["tool_input"], "command": rewritten},
            }
        }

    return rtk_rewrite


def rtk_hook(search_path: str | None = None) -> RtkHook:
    """Build the hook from the `rtk` on `search_path` (default: `PATH`), or a warning."""
    found = shutil.which(RTK_BINARY, path=search_path)
    if found is None:
        warning = RunWarning(
            RTK_MISSING,
            "rtk is not on PATH: worker shell output reaches the model unfiltered. "
            "Install rtk to enable the token-saving hook.",
        )
        logger.warning(warning.message)
        return RtkHook(binary=None, warnings=(warning,))
    binary = Path(found)
    matcher = HookMatcher(matcher=SHELL_TOOL, hooks=[make_rewrite_hook(binary)])
    return RtkHook(binary=binary, matchers=[matcher])
