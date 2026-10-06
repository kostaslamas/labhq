"""labhq's own tmux server, on a dedicated socket, driven one command at a time.

Every command runs with the client environment from `labhq.adapters.tmux.environment`, never
with this process's environment, and with labhq's configuration file, so the server that the
first command starts holds only the allowlist and copies nothing from later clients. The
configuration is applied again before each session, in case the server outlived a labhq
that started it with an older file.

The owner can watch or take over a run with `tmux -L <socket> attach -t <session>`.
"""

import contextlib
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from labhq.adapters.tmux.environment import client_environment

# `exit-empty off` keeps the server up between runs. An empty `update-environment` copies
# nothing from a client into a new session. `remain-on-exit` keeps a finished agent's pane,
# so its last screen and exit status can still be read.
SERVER_OPTIONS: tuple[tuple[str, ...], ...] = (
    ("set-option", "-s", "exit-empty", "off"),
    ("set-option", "-g", "update-environment", ""),
    ("set-option", "-g", "remain-on-exit", "on"),
    ("set-option", "-g", "remain-on-exit-format", ""),
    ("set-option", "-g", "history-limit", "50000"),
)
SESSION_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
COLUMNS, ROWS = 200, 50


class TmuxError(RuntimeError):
    pass


class TmuxMissingError(TmuxError):
    """tmux is not installed; the tmux adapter cannot run on this machine."""


@dataclass(frozen=True)
class PaneState:
    dead: bool
    exit_status: int | None


def config_text() -> str:
    return "".join(" ".join(_quote(word) for word in option) + "\n" for option in SERVER_OPTIONS)


def _quote(word: str) -> str:
    return '""' if word == "" else word


class TmuxServer:
    def __init__(
        self,
        *,
        socket: str,
        state_dir: Path,
        environ: Mapping[str, str] | None = None,
        binary: str | None = None,
    ) -> None:
        found = binary or shutil.which("tmux")
        if found is None:
            raise TmuxMissingError("tmux is not installed; install it to use the tmux adapter")
        self.socket = socket
        self.binary = found
        self.state_dir = state_dir
        self._environ = environ if environ is not None else os.environ

    @property
    def config_path(self) -> Path:
        return self.state_dir / "tmux.conf"

    def run(self, *args: str, client_env: Mapping[str, str] | None = None) -> str:
        """Run one tmux command. `client_env` exists for tests that prove what leaks."""
        env = client_environment(self._environ) if client_env is None else dict(client_env)
        result = subprocess.run(
            [self.binary, "-L", self.socket, "-f", str(self._config()), *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise TmuxError(f"tmux {args[0]} exited {result.returncode}: {result.stderr.strip()}")
        return result.stdout

    def ensure_started(self) -> None:
        self.run("start-server")
        for option in SERVER_OPTIONS:
            self.run(*option)

    def new_session(
        self,
        name: str,
        *,
        cwd: Path,
        argv: Sequence[str],
        variables: Mapping[str, str],
        client_env: Mapping[str, str] | None = None,
    ) -> None:
        if not SESSION_NAME.match(name):
            raise TmuxError(f"unsafe session name {name!r}")
        self.ensure_started()
        assignments = [word for item in variables.items() for word in ("-e", "=".join(item))]
        # More than one word after `--` is executed directly, without a shell.
        self.run(
            "new-session",
            "-d",
            "-s",
            name,
            "-x",
            str(COLUMNS),
            "-y",
            str(ROWS),
            "-c",
            str(cwd),
            *assignments,
            "--",
            *argv,
            client_env=client_env,
        )

    def capture(self, name: str) -> str:
        """The pane's whole history and screen, joined lines, trailing blank lines dropped."""
        text = self.run("capture-pane", "-p", "-J", "-S", "-", "-t", f"={name}:")
        return "\n".join(line.rstrip() for line in text.rstrip().splitlines())

    def list_sessions(self) -> list[str]:
        """Names on labhq's private server, including sessions with a dead pane."""
        return self.run("list-sessions", "-F", "#{session_name}").splitlines()

    def respawn_session(
        self, name: str, *, cwd: Path, argv: Sequence[str], variables: Mapping[str, str]
    ) -> None:
        """Restart a dead managed pane in its existing named session."""
        assignments = [word for item in variables.items() for word in ("-e", "=".join(item))]
        self.run(
            "respawn-pane",
            "-k",
            "-t",
            f"={name}:",
            "-c",
            str(cwd),
            *assignments,
            "--",
            *argv,
        )

    def send_keys(self, name: str, *keys: str, literal: bool = False) -> None:
        flags = ("-l",) if literal else ()
        self.run("send-keys", "-t", f"={name}:", *flags, *keys)

    def pane_state(self, name: str) -> PaneState:
        out = self.run(
            "list-panes", "-t", f"={name}:", "-F", "#{pane_dead} #{pane_dead_status}"
        ).split()
        dead = bool(out) and out[0] == "1"
        status = int(out[1]) if dead and len(out) > 1 and out[1].lstrip("-").isdigit() else None
        return PaneState(dead=dead, exit_status=status)

    def pane_pid(self, name: str) -> int | None:
        """The process the pane runs: the agent CLI itself, as it is started without a shell."""
        out = self.run("list-panes", "-t", f"={name}:", "-F", "#{pane_pid}").split()
        return int(out[0]) if out and out[0].isdigit() else None

    def has_session(self, name: str) -> bool:
        try:
            self.run("has-session", "-t", f"={name}")
        except TmuxError:
            return False
        return True

    def kill_session(self, name: str) -> None:
        if self.has_session(name):
            self.run("kill-session", "-t", f"={name}")

    def show_environment(self, name: str) -> dict[str, str]:
        lines = self.run("show-environment", "-t", f"={name}").splitlines()
        return dict(line.split("=", 1) for line in lines if "=" in line and line[0] != "-")

    def kill_server(self) -> None:
        with contextlib.suppress(TmuxError):
            self.run("kill-server")

    def _config(self) -> Path:
        path = self.config_path
        text = config_text()
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return path
