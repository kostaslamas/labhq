"""`labhq agent add --adapter ollama` works because the adapter is registered, nothing more."""

from pathlib import Path

import pytest

from tests.cli.conftest import Cli
from tests.worktrees.conftest import isolated_git, remote, repo

# The CLI tests' git isolation and scratch repository, shared rather than copied.
__all__ = ["isolated_git", "remote", "repo"]


def test_an_agent_can_be_added_on_the_ollama_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo: Path
) -> None:
    monkeypatch.setenv("LABHQ_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("LABHQ_DATABASE_URL", raising=False)
    cli = Cli(tmp_path / "data")
    cli.ok("init")
    cli.ok("project", "add", "site", "--repo", str(repo))

    added = cli.ok(
        "agent", "add", "--project", "site", "--role", "writer", "--title", "Writer",
        "--adapter", "ollama",
    )  # fmt: skip

    assert "(writer, ollama)" in added
    [agent] = cli.rows("SELECT adapter FROM agents")
    assert agent["adapter"] == "ollama"
