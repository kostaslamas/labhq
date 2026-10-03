import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from labhq.cli import app
from labhq.settings import DATABASE_FILENAME
from tests.worktrees.conftest import isolated_git, remote, repo

# The CLI drives real git against a local bare remote, under the worktree tests' isolation.
__all__ = ["isolated_git", "remote", "repo"]

# CI sets FORCE_COLOR, so rich styles help text and splits option names with escapes.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    return _ANSI.sub("", text)


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A scratch data directory per test; CI's own LABHQ_DATA_DIR must stay untouched."""
    path = tmp_path / "data"
    monkeypatch.setenv("LABHQ_DATA_DIR", str(path))
    monkeypatch.delenv("LABHQ_DATABASE_URL", raising=False)
    return path


class Cli:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._runner = CliRunner()

    def __call__(self, *args: str) -> Result:
        return self._runner.invoke(app, list(args))

    def ok(self, *args: str) -> str:
        result = self(*args)
        assert result.exit_code == 0, (args, result.output, result.exception)
        return plain(result.stdout)

    def rows(self, sql: str, *params: Any) -> list[sqlite3.Row]:
        with closing(sqlite3.connect(self.data_dir / DATABASE_FILENAME)) as connection:
            connection.row_factory = sqlite3.Row
            return list(connection.execute(sql, params))


@pytest.fixture
def cli(data_dir: Path) -> Iterator[Cli]:
    yield Cli(data_dir)
