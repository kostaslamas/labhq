"""Shared pieces of the inventory tests: a scanner on a fixture home and fake processes."""

import subprocess
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

import psutil
import pytest

from labhq.adapters.tmux import default_kinds
from labhq.adoption.discovery import RunningAgent
from labhq.clock import FakeClock
from labhq.inventory.model import SessionState
from labhq.inventory.scan import SessionScanner
from labhq.inventory.settings import InventorySettings
from tests.scheduler.conftest import sessions


class FixedProbe:
    """Reports a chosen state for every process."""

    def __init__(self, state: SessionState = SessionState.IDLE) -> None:
        self.state = state

    def states(self, agents: Iterable[RunningAgent]) -> dict[int, SessionState]:
        return {agent.pid: self.state for agent in agents}


class FakeProcess:
    def __init__(self, pid: int, command: list[str], cwd: Path) -> None:
        self.pid = pid
        self.info = {"pid": pid, "cmdline": command, "create_time": 1_700_000_000.0}
        self._cwd = cwd

    def cwd(self) -> str:
        return str(self._cwd)


def git(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=path,
        check=True,
        capture_output=True,
    )


def make_repo(path: Path, subject: str = "first commit") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", subject)
    return path


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        monkeypatch.delenv(name, raising=False)
    return home


Scan = Callable[..., SessionScanner]


@pytest.fixture
def scanner(home: Path) -> Scan:
    def build(
        processes: list[FakeProcess] | None = None,
        state: SessionState = SessionState.IDLE,
        **settings: object,
    ) -> SessionScanner:
        return SessionScanner(
            settings=InventorySettings(use_gh=False, **settings),  # type: ignore[arg-type]
            clock=FakeClock(datetime(2026, 6, 1, tzinfo=UTC)),
            processes=lambda: processes or [],
            probe=FixedProbe(state),
            home=home,
            environ={},
        )

    return build


@pytest.fixture
def make_ids() -> Callable[[], str]:
    """Distinct, valid session ids for tests that need many Claude conversations."""
    counter = iter(range(1, 10_000))
    return lambda: f"{next(counter):08d}-1111-4111-8111-111111111111"


__all__ = ["FakeProcess", "FixedProbe", "default_kinds", "git", "make_repo", "psutil", "sessions"]
