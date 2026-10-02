from pathlib import Path

import pytest

from labhq.worktrees.git import run_git


@pytest.fixture(autouse=True)
def isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's git config, helpers and identity out of every test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for variable in ("GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_DIR", "GIT_WORK_TREE"):
        monkeypatch.delenv(variable, raising=False)
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "labhq test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@labhq.invalid")


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    path = tmp_path / "remote.git"
    run_git("init", "--quiet", "--bare", "--initial-branch=main", str(path), cwd=tmp_path)
    return path


@pytest.fixture
def repo(tmp_path: Path, remote: Path) -> Path:
    """A project repository with one commit on `main`, published to `remote`."""
    path = tmp_path / "project"
    run_git("init", "--quiet", "--initial-branch=main", str(path), cwd=tmp_path)
    (path / "README.md").write_text("project\n", encoding="utf-8")
    run_git("add", "README.md", cwd=path)
    run_git("commit", "--quiet", "-m", "init", cwd=path)
    run_git("remote", "add", "origin", str(remote), cwd=path)
    run_git("push", "--quiet", "origin", "main", cwd=path)
    return path
