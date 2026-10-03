"""The owner's checkout after the move: rules excluded, uncommitted work untouched, push
deterred by the environment alone."""

from sqlalchemy import select

from labhq.adoption import RULES_RELATIVE_PATH, rules_message
from labhq.adoption.session import send_message, session_name
from labhq.callcenter.status.ingest import STATUS_RELATIVE_PATH
from labhq.db.models import StatusUpdate
from labhq.worktrees.git import run_git
from tests.adoption.conftest import World, adopt, wait_for


def refs(world: World) -> str:
    remote = world.repo.parent / "remote.git"
    return run_git("for-each-ref", "--format=%(refname) %(objectname)", cwd=remote)


async def test_the_rules_file_is_excluded_and_git_status_does_not_show_it(world: World) -> None:
    await adopt(world)

    rules = world.repo / RULES_RELATIVE_PATH
    assert rules.exists()
    assert "Never push or merge" in rules.read_text(encoding="utf-8")
    exclude = (world.repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert ".labhq/" in exclude.splitlines()
    status = run_git("status", "--porcelain", "--untracked-files=all", cwd=world.repo)
    assert ".labhq" not in status
    run_git("add", "-A", cwd=world.repo)
    assert ".labhq" not in run_git("diff", "--cached", "--name-only", cwd=world.repo)


async def test_uncommitted_changes_stay_unchanged_and_appear_in_the_status(world: World) -> None:
    (world.repo / "README.md").write_text("half-done edit\n", encoding="utf-8")
    (world.repo / "notes.txt").write_text("untracked notes\n", encoding="utf-8")
    before = {name: (world.repo / name).read_bytes() for name in ("README.md", "notes.txt")}

    _, agent_id = await adopt(world)

    assert {name: (world.repo / name).read_bytes() for name in before} == before
    async with world.sessions() as db:
        update = await db.scalar(
            select(StatusUpdate).where(StatusUpdate.agent_id == agent_id).limit(1)
        )
    assert update is not None
    assert set(update.fields["refs"]) == {"README.md", "notes.txt"}
    assert "left in place" in update.fields["summary"]
    status_file = (world.repo / STATUS_RELATIVE_PATH).read_text(encoding="utf-8")
    assert "README.md" in status_file


async def test_git_push_from_the_adopted_agent_fails_through_the_environment_alone(
    world: World,
) -> None:
    config = (world.repo / ".git" / "config").read_bytes()
    before = refs(world)
    original, _ = await adopt(world)
    name = session_name(original.pid)
    # The fake kind installs no hook: only the environment stands in the way.
    assert world.kinds.get("fake-cli").hooks is None
    await wait_for(lambda: rules_message() in world.inbox, "the rules message")

    send_message(world.private, name, "PUSH")
    await wait_for(lambda: "push-exit=" in world.private.capture(name), "the push attempt")

    screen = world.private.capture(name)
    assert "push-exit=0" not in screen
    assert refs(world) == before
    assert (world.repo / ".git" / "config").read_bytes() == config
