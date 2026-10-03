"""The continued agent's session on the private tmux server, and what it reports.

The session runs the kind's `continue_` template in the original working directory, with
the launch integration of a labhq run (statusline, turn signal, push guard hook where the
CLI has one) and the adopted environment. Its turn signal and statusline land in a state
directory of its own, which the engine checks read after the move.
"""

import hashlib
import json
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from labhq.adapters.tmux.adapter import SIGNAL_FILE, STATUSLINE_FILE, guard_hook_command
from labhq.adapters.tmux.agents import LAUNCHES, AgentKind, LaunchContext, SessionIdSource
from labhq.adapters.tmux.environment import client_environment
from labhq.adapters.tmux.server import TmuxServer
from labhq.adoption.rules import RULES_RELATIVE_PATH, appends, rules_text
from labhq.worktrees import adopted_environment

# The statusline's own key for the conversation, when the turn signal names none.
STATUSLINE_SESSION_KEY = "session_id"


@dataclass(frozen=True)
class AdoptedSession:
    name: str
    cwd: Path
    state_dir: Path

    @property
    def signal_path(self) -> Path:
        return self.state_dir / SIGNAL_FILE

    @property
    def statusline_path(self) -> Path:
        return self.state_dir / STATUSLINE_FILE


def session_name(pid: int) -> str:
    return f"adopted-{pid}"


def continue_argv(
    kind: AgentKind, session: AdoptedSession, *, python: str, sandbox: Sequence[str]
) -> list[str]:
    if kind.continue_ is None:
        raise ValueError(f"agent kind {kind.name!r} cannot continue a conversation")
    context = LaunchContext(
        python=python,
        signal_path=session.signal_path,
        statusline_path=session.statusline_path,
        guard_hook=guard_hook_command(python),
    )
    values = {
        "rules": rules_text(),
        "rules_file": str(session.cwd / RULES_RELATIVE_PATH),
        "signal_path": str(session.signal_path),
        "statusline_path": str(session.statusline_path),
        "guard_hook": context.guard_hook,
    }
    words = [word.format_map(values) for word in kind.continue_]
    launch = LAUNCHES[kind.launch](context) if kind.launch is not None else []
    rules = [word.format_map(values) for word in kind.rules_words] if appends(kind) else []
    return [*sandbox, words[0], *launch, *rules, *words[1:]]


def start_session(
    server: TmuxServer,
    kind: AgentKind,
    session: AdoptedSession,
    *,
    environ: Mapping[str, str],
    python: str,
    sandbox: Sequence[str],
) -> list[str]:
    session.state_dir.mkdir(parents=True, exist_ok=True)
    for stale in (session.signal_path, session.statusline_path):
        stale.unlink(missing_ok=True)
    argv = continue_argv(kind, session, python=python, sandbox=sandbox)
    variables = adopted_environment(session.cwd, client_environment(environ))
    server.new_session(session.name, cwd=session.cwd, argv=argv, variables=variables)
    return argv


def send_message(server: TmuxServer, name: str, text: str) -> None:
    server.send_keys(name, text, literal=True)
    server.send_keys(name, "Enter")


def read_document(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def reported_session(kind: AgentKind, session: AdoptedSession) -> str | None:
    """The conversation id the agent reported last, from its turn signal or statusline."""
    if kind.session_id is SessionIdSource.FIXED:
        # One conversation per directory, named by the kind itself.
        return kind.session_key
    keys = [key for key in (kind.session_key, STATUSLINE_SESSION_KEY) if key]
    for path in (session.signal_path, session.statusline_path):
        document = read_document(path) or {}
        for key in keys:
            if document.get(key):
                return str(document[key])
    return None


def describe(argv: Sequence[str]) -> str:
    return shlex.join(argv)


def file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
