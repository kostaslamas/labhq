"""The real Codex entry of the tmux adapter, with the fake `codex` first on PATH.

Each test gets its own private tmux server and its own `FAKE_CODEX_HOME`, so sessions never
leak between tests. The adapter receives the PATH through its environment, as a worker's
session would; nothing in labhq knows the binary is fake.
"""

import os
import shlex
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from labhq.adapters.tmux import AgentKinds, TmuxAdapter, TmuxServer, default_kinds
from labhq.clock import SystemClock
from tests.adapters.tmux.conftest import FAST, require_tmux

FAKE_CODEX = Path(__file__).with_name("fake_codex.py")
CODEX_CONFIG: dict[str, object] = {"agent": "codex", **FAST}


@dataclass
class FakeCodex:
    server: TmuxServer
    environ: dict[str, str]
    home: Path
    kinds: AgentKinds

    def adapter(self) -> TmuxAdapter:
        return TmuxAdapter(
            server=self.server, kinds=self.kinds, clock=SystemClock(), environ=self.environ
        )

    def session_files(self) -> list[Path]:
        return sorted((self.home / "sessions").glob("*.json"))


def install_fake_codex(root: Path) -> tuple[dict[str, str], Path]:
    """A `codex` shim in `root/bin`; returns an environment with it first on PATH."""
    bin_dir, home = root / "bin", root / "codex-home"
    bin_dir.mkdir(parents=True)
    shim = bin_dir / "codex"
    command = shlex.join([sys.executable, str(FAKE_CODEX)])
    shim.write_text(
        f'#!/bin/sh\nFAKE_CODEX_HOME={shlex.quote(str(home))} exec {command} "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    return {**os.environ, "PATH": path}, home


@pytest.fixture
def fake_codex(tmp_path: Path) -> Iterator[FakeCodex]:
    require_tmux()
    environ, home = install_fake_codex(tmp_path)
    server = TmuxServer(
        socket=f"labhq-test-{uuid.uuid4().hex[:12]}",
        state_dir=tmp_path / "tmux",
        environ=environ,
    )
    try:
        yield FakeCodex(server=server, environ=environ, home=home, kinds=default_kinds.copy())
    finally:
        server.kill_server()
