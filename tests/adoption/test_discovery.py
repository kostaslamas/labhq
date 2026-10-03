"""Discovery finds running agents from the process table and reads nothing else."""

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from labhq.adapters.tmux import AgentKinds, default_kinds
from labhq.adoption import discover
from labhq.adoption.discovery import adoptable, kind_of
from tests.adoption.conftest import FAKE_CLI, KIND, fake_kind

# Where the CLIs keep sessions and logins, and where git and ssh keep credentials.
PRIVATE_DIRS = (".claude", ".codex", ".gemini", ".aider", ".ssh", ".config/gh")
PRIVATE_FILES = (".claude.json", ".git-credentials", ".netrc")


class OpenedPaths:
    """Every path this process opens or lists while `recording` is on (PEP 578 audit hook)."""

    def __init__(self) -> None:
        self.recording = False
        self.paths: list[str] = []
        sys.addaudithook(self._hook)

    def _hook(self, event: str, args: tuple[Any, ...]) -> None:
        if not self.recording or not (event == "open" or event.startswith("os.")):
            return
        if args and isinstance(args[0], (str, bytes, Path)):
            path = args[0].decode() if isinstance(args[0], bytes) else str(args[0])
            self.paths.append(path)


AUDIT = OpenedPaths()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home with every agent's session and credential store in it, to be left unread."""
    home = tmp_path / "home"
    for directory in PRIVATE_DIRS:
        (home / directory).mkdir(parents=True)
        (home / directory / "secret").write_text("do not read\n", encoding="utf-8")
    for name in PRIVATE_FILES:
        (home / name).write_text("do not read\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def agent_process(tmp_path: Path) -> Iterator[subprocess.Popen[bytes]]:
    workdir = tmp_path / "checkout"
    workdir.mkdir()
    command = [sys.executable, str(FAKE_CLI), "--store", str(tmp_path / "store")]
    with subprocess.Popen(
        command, cwd=workdir, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL
    ) as process:
        try:
            yield process
        finally:
            process.kill()


def kinds_with_fake(tmp_path: Path) -> AgentKinds:
    kinds = default_kinds.copy()
    kinds.register(fake_kind(tmp_path / "store"))
    return kinds


def test_discovery_finds_the_agent_and_its_directory_reading_no_private_file(
    tmp_path: Path, home: Path, agent_process: subprocess.Popen[bytes]
) -> None:
    kinds = kinds_with_fake(tmp_path)

    AUDIT.paths.clear()
    AUDIT.recording = True
    try:
        found = discover(kinds)
    finally:
        AUDIT.recording = False

    mine = [agent for agent in found if agent.pid == agent_process.pid]
    assert len(mine) == 1
    assert mine[0].kind == KIND
    assert mine[0].cwd == tmp_path / "checkout"
    private = [home / name for name in (*PRIVATE_DIRS, *PRIVATE_FILES)]
    touched = [path for path in AUDIT.paths if any(path.startswith(str(p)) for p in private)]
    assert touched == []
    if sys.platform.startswith("linux"):
        # On Linux the process table is /proc, so the hook must see it, or the check above
        # would prove nothing; nothing outside it is opened. macOS and Windows answer
        # through system calls, so no file is opened there at all.
        assert AUDIT.paths, "the audit hook saw nothing; the check would prove nothing"
        assert all(path.startswith("/proc") for path in AUDIT.paths), AUDIT.paths


def test_a_process_that_is_no_known_agent_is_not_listed(tmp_path: Path) -> None:
    with subprocess.Popen([sys.executable, "-c", "input()"], stdin=subprocess.PIPE) as process:
        try:
            assert process.pid not in {agent.pid for agent in discover(kinds_with_fake(tmp_path))}
        finally:
            process.kill()


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        (["claude", "--continue"], "claude-code"),
        (["/usr/bin/node", "/opt/bin/gemini"], "gemini"),
        (["/usr/bin/python3", "/home/u/.local/bin/aider"], "aider"),
        (["codex"], "codex"),
        (["python3", "-m", "http.server"], None),
        (["/bin/sh", "-c", "claude"], None),
    ],
)
def test_the_program_is_one_of_the_first_two_words(command: list[str], kind: str | None) -> None:
    found = kind_of(command, adoptable(default_kinds))
    assert (found.name if found else None) == kind
