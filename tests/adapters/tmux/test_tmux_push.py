"""`git push` from the fake agent's worktree fails, with the guard hook and without it."""

from pathlib import Path

import pytest

from labhq.adapters import RunRequest
from labhq.adapters.contract import run_once
from labhq.worktrees import Worktree, Worktrees
from labhq.worktrees.git import run_git
from tests.adapters.tmux.conftest import AdapterMaker, agent_config
from tests.worktrees.gitrepo import commit_file


@pytest.fixture
def worktree(repo: Path, tmp_path: Path) -> Worktree:
    worktree = Worktrees(repo, tmp_path / "worktrees").create(9, "push attempt")
    commit_file(worktree.path, "work.txt")
    return worktree


def remote_refs(remote: Path) -> str:
    return run_git("for-each-ref", "--format=%(refname) %(objectname)", cwd=remote)


async def push_screen(make_adapter: AdapterMaker, worktree: Worktree, kind: str) -> str:
    request = RunRequest(prompt="PUSH", cwd=worktree.path, config=agent_config(kind))
    events, _ = await run_once(make_adapter(), request)
    return "\n".join(line for event in events for line in event.payload.get("lines", []))


async def test_the_hook_denies_the_push_before_it_runs(
    make_adapter: AdapterMaker, worktree: Worktree, remote: Path
) -> None:
    before = remote_refs(remote)

    screen = await push_screen(make_adapter, worktree, "fake-agent")

    assert "push=denied-by-hook" in screen
    assert remote_refs(remote) == before


async def test_without_the_hook_the_push_fails_at_the_transport(
    make_adapter: AdapterMaker, worktree: Worktree, remote: Path
) -> None:
    before = remote_refs(remote)

    screen = await push_screen(make_adapter, worktree, "fake-agent-nohook")

    assert "push-exit=" in screen
    assert "push-exit=0" not in screen
    assert remote_refs(remote) == before
