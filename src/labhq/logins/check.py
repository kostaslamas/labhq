"""Is a tool logged in? Its own status command answers, or the login dialog on its screen.

Only the tool's documented status output is read: an exit code, the one boolean of a JSON
status, or a phrase of the text. No credential file or token is ever opened (ADR 0001).
"""

import json
import re
import subprocess
from enum import StrEnum
from typing import Protocol

from labhq.logins.tools import LoginTool


class LoginState(StrEnum):
    LOGGED_IN = "logged_in"
    LOGGED_OUT = "logged_out"
    # The tool has no status command and no screen was given, or its binary is missing.
    UNKNOWN = "unknown"


class CommandRunner(Protocol):
    def __call__(self, argv: tuple[str, ...], timeout: float) -> tuple[int, str] | None:
        """Exit code and standard output, or None when the program is missing or timed out."""
        ...


def run_command(argv: tuple[str, ...], timeout: float) -> tuple[int, str] | None:
    try:
        result = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode, result.stdout


def check_login(
    tool: LoginTool,
    *,
    runner: CommandRunner = run_command,
    timeout: float = 15.0,
    screen: str | None = None,
) -> LoginState:
    """Status command first; a tool without one is judged by `screen` when given."""
    if tool.status is not None:
        answer = runner(tool.status, timeout)
        return LoginState.UNKNOWN if answer is None else _from_status(tool, *answer)
    if screen is not None and tool.screen_pattern is not None:
        shown = re.search(tool.screen_pattern, screen, re.DOTALL) is not None
        return LoginState.LOGGED_OUT if shown else LoginState.LOGGED_IN
    return LoginState.UNKNOWN


def _from_status(tool: LoginTool, code: int, output: str) -> LoginState:
    if tool.status_json_key is not None:
        try:
            document = json.loads(output)
        except ValueError:
            return LoginState.LOGGED_OUT
        # Only this one field is read; everything else in the answer is ignored.
        ok = isinstance(document, dict) and document.get(tool.status_json_key) is True
        return LoginState.LOGGED_IN if ok else LoginState.LOGGED_OUT
    if code != 0:
        return LoginState.LOGGED_OUT
    if tool.logged_out_pattern and re.search(tool.logged_out_pattern, output):
        return LoginState.LOGGED_OUT
    return LoginState.LOGGED_IN
