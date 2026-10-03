from pathlib import Path

from labhq.memory import MEMORY_RELATIVE_PATH
from labhq.worktrees import Worktrees
from labhq.worktrees.git import run_git
from tests.memory.conftest import MemoryWorld
from tests.worktrees.conftest import isolated_git, remote, repo

__all__ = ["isolated_git", "remote", "repo"]


async def test_git_add_all_in_a_task_worktree_does_not_stage_memory(
    world: MemoryWorld, repo: Path, tmp_path: Path
) -> None:
    lead = await world.agent("lead")
    task_id = world.task_ids[0]
    worktree = Worktrees(repo, tmp_path / "worktrees").create(task_id, "Parser")

    await world.run(lead, task_id=task_id, cwd=worktree.path, writes="Parser is half done.\n")
    (worktree.path / "parser.py").write_text("pass\n", encoding="utf-8")
    run_git("add", "-A", cwd=worktree.path)

    assert (worktree.path / MEMORY_RELATIVE_PATH).is_file()
    staged = run_git("diff", "--cached", "--name-only", cwd=worktree.path).split()
    assert staged == ["parser.py"]
