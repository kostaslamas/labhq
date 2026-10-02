"""A worker cannot push from its worktree even if the hook never runs."""

from pathlib import Path

import pytest

from labhq.worktrees import Worktree, Worktrees, worker_environment
from labhq.worktrees.git import GitError, run_git
from tests.worktrees.gitrepo import commit_file, head


@pytest.fixture
def worktree(repo: Path, tmp_path: Path) -> Worktree:
    worktree = Worktrees(repo, tmp_path / "worktrees").create(7, "guarded")
    commit_file(worktree.path, "work.txt")
    return worktree


def remote_refs(remote: Path) -> str:
    return run_git("for-each-ref", "--format=%(refname) %(objectname)", cwd=remote)


@pytest.mark.parametrize(
    "push",
    [
        ("push", "origin", "HEAD"),
        ("push", "origin", "HEAD:refs/heads/main"),
        ("push", "--set-upstream", "origin", "HEAD"),
        ("push", "--mirror", "origin"),
    ],
    ids=" ".join,
)
def test_push_to_the_remote_fails_from_the_worker_environment(
    worktree: Worktree, remote: Path, push: tuple[str, ...]
) -> None:
    before = remote_refs(remote)

    with pytest.raises(GitError):
        run_git(*push, cwd=worktree.path, env=worker_environment())

    assert remote_refs(remote) == before


def test_push_to_an_explicit_url_fails(worktree: Worktree, remote: Path) -> None:
    before = remote_refs(remote)

    for url in (str(remote), remote.as_uri()):
        with pytest.raises(GitError):
            run_git("push", url, "HEAD", cwd=worktree.path, env=worker_environment())

    assert remote_refs(remote) == before


def test_push_to_a_remote_added_by_the_worker_fails(worktree: Worktree, remote: Path) -> None:
    env = worker_environment()
    run_git("remote", "add", "sneaky", str(remote), cwd=worktree.path, env=env)

    with pytest.raises(GitError):
        run_git("push", "sneaky", "HEAD", cwd=worktree.path, env=env)

    assert "labhq/task-7" not in remote_refs(remote)


def test_push_config_does_not_leak_into_the_main_repository(
    worktree: Worktree, repo: Path, remote: Path
) -> None:
    # The engine publishes from the main checkout once the push is approved.
    run_git("push", "--quiet", "origin", worktree.branch, cwd=repo)

    assert head(remote, worktree.branch) == head(repo, worktree.branch)
