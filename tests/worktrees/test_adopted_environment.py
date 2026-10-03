"""The adopted environment deters a push from the main checkout; it does not prevent one.

The repository's config is never written. Dropping the environment's entries restores the
push, which is why the docs and the adoption confirmation recommend a sandbox (ADR 0005).
"""

import os
import subprocess
from pathlib import Path

from labhq.worktrees import PUSH_DISABLED_URL, adopted_environment
from labhq.worktrees.environment import worker_environment
from labhq.worktrees.git import run_git
from tests.worktrees.gitrepo import commit_file


def push(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "push", "origin", "HEAD:refs/heads/main"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def refs(remote: Path) -> str:
    return run_git("for-each-ref", "--format=%(refname) %(objectname)", cwd=remote)


def test_every_remote_push_url_points_at_the_disabled_url(repo: Path, remote: Path) -> None:
    run_git("remote", "add", "mirror", str(remote), cwd=repo)

    env = adopted_environment(repo, {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"})

    pairs = {
        env[f"GIT_CONFIG_KEY_{index}"]: env[f"GIT_CONFIG_VALUE_{index}"]
        for index in range(int(env["GIT_CONFIG_COUNT"]))
    }
    assert pairs["remote.origin.pushurl"] == PUSH_DISABLED_URL
    assert pairs["remote.mirror.pushurl"] == PUSH_DISABLED_URL
    assert pairs[f"url.{PUSH_DISABLED_URL}.pushInsteadOf"] == ""
    # The worker environment's own entries stay.
    assert pairs["credential.helper"] == ""


def test_the_environment_alone_deters_the_push_and_the_config_is_unchanged(
    repo: Path, remote: Path
) -> None:
    commit_file(repo, "work.txt")
    config = (repo / ".git" / "config").read_bytes()
    before = refs(remote)

    result = push(repo, adopted_environment(repo, dict(os.environ)))

    assert result.returncode != 0
    assert refs(remote) == before
    assert (repo / ".git" / "config").read_bytes() == config


def test_dropping_the_entries_restores_the_push_so_it_only_deters(repo: Path, remote: Path) -> None:
    commit_file(repo, "work.txt")
    env = adopted_environment(repo, dict(os.environ))
    # What `env -u GIT_CONFIG_COUNT git push` does: the repository's own push URL applies.
    del env["GIT_CONFIG_COUNT"]

    result = push(repo, env)

    assert result.returncode == 0, result.stderr
    assert refs(remote) != ""


def test_the_base_worker_environment_is_kept(repo: Path) -> None:
    base = {"PATH": "/usr/bin", "SSH_AUTH_SOCK": "/tmp/agent", "GH_TOKEN": "secret"}

    env = adopted_environment(repo, base)

    worker = worker_environment(base)
    assert "SSH_AUTH_SOCK" not in env and "GH_TOKEN" not in env
    assert {name: env[name] for name in worker if not name.startswith("GIT_CONFIG")} == {
        name: value for name, value in worker.items() if not name.startswith("GIT_CONFIG")
    }
