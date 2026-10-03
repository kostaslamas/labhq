import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from click.testing import Result
from typer.testing import CliRunner

from labhq.cli import app
from labhq.settings import DATABASE_FILENAME
from tests.worktrees.conftest import isolated_git, remote, repo

# The CLI runs real git against local repositories, under the worktree tests' isolation.
__all__ = ["isolated_git", "remote", "repo"]

# CI sets FORCE_COLOR, so rich styles help text and splits option names with escapes.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class Cli:
    data_dir: Path

    def __call__(self, *args: str) -> Result:
        return CliRunner().invoke(app, list(args))

    def ok(self, *args: str) -> str:
        result = self(*args)
        assert result.exit_code == 0, (result.output, result.exception)
        return result.stdout

    def rows(self, sql: str, *params: Any) -> list[tuple[Any, ...]]:
        with closing(sqlite3.connect(self.data_dir / DATABASE_FILENAME)) as connection:
            return connection.execute(sql, params).fetchall()


@pytest.fixture
def cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Cli:
    """The CLI against a scratch data directory; `LABHQ_DATABASE_URL` must not leak in."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("LABHQ_DATA_DIR", str(data_dir))
    monkeypatch.delenv("LABHQ_DATABASE_URL", raising=False)
    return Cli(data_dir)
