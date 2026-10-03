from sqlalchemy import select

from labhq.db.models import RunEvent
from labhq.memory import truncate_oldest
from labhq.runs.lifecycle import MEMORY_EVENT
from tests.memory.conftest import MAX_CHARS, MemoryWorld

NOTICE = "oldest"


def numbered(count: int) -> str:
    return "".join(f"line {index:03d} of the manager's notes\n" for index in range(count))


def test_text_within_the_limit_is_kept_whole() -> None:
    assert truncate_oldest("a\nb\n", 10) == ("a\nb\n", 0)


def test_the_oldest_lines_go_first() -> None:
    assert truncate_oldest("old\nmid\nnew\n", 8) == ("mid\nnew\n", 1)


def test_one_line_over_the_limit_keeps_its_tail() -> None:
    assert truncate_oldest("first\n" + "x" * 20, 5) == ("xxxxx", 1)


async def test_memory_over_the_limit_is_stored_without_its_oldest_lines(
    world: MemoryWorld,
) -> None:
    manager = await world.agent("manager")
    text = numbered(20)
    assert len(text) > MAX_CHARS

    run = await world.run(manager, writes=text)

    stored = world.memory.read(manager)
    assert len(stored) <= MAX_CHARS
    assert text.endswith(stored)
    assert stored.startswith("line ")
    assert "line 000" not in stored
    assert "line 019" in stored
    async with world.sessions() as db:
        event = await db.scalar(
            select(RunEvent).where(RunEvent.run_id == run.run_id, RunEvent.kind == MEMORY_EVENT)
        )
    assert event is not None
    dropped = event.payload["dropped_lines"]
    assert dropped == text.count("\n") - stored.count("\n")

    await world.run(manager)
    assert f"its {NOTICE} {dropped} line(s) were dropped" in world.last_prompt()
    assert stored.rstrip() in world.last_prompt()


async def test_the_notice_goes_once_memory_fits_again(world: MemoryWorld) -> None:
    manager = await world.agent("manager")
    await world.run(manager, writes=numbered(20))
    await world.run(manager, writes="Condensed.\n")

    await world.run(manager)

    assert "were dropped" not in world.last_prompt()
    assert "Condensed." in world.last_prompt()
