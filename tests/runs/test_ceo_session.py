"""An SDK CEO keeps one conversation across the owner's messages, as the tmux kinds do."""

from sqlalchemy import update

from labhq.ceochat import message_prompt, message_reason
from labhq.db.models import Agent
from tests.runs.conftest import World
from tests.runs.helpers import stored_run, use_adapter


async def _make_ceo(world: World) -> None:
    await use_adapter(world, "claude")
    async with world.sessions() as db:
        await db.execute(
            update(Agent).where(Agent.id == world.agent_id).values(role="ceo", project_id=None)
        )
        await db.commit()


async def _owner_turn(world: World, text: str) -> int:
    run = await world.service.execute(
        agent_id=world.agent_id, task_id=None, prompt=message_prompt(message_reason(text, []))
    )
    return run.id


async def test_two_owner_messages_reuse_one_sdk_session(world: World) -> None:
    await _make_ceo(world)

    first = await _owner_turn(world, "Plan the site launch.")
    second = await _owner_turn(world, "Which project is late?")

    assert [options.resume for options in world.claude.options] == [None, "stub-session-1"]
    assert (await stored_run(world, second)).session_id_before == "stub-session-1"
    assert (await stored_run(world, first)).session_id_after == "stub-session-1"
    # The resumed turn carries the owner's words alone; the session already has the rest.
    assert world.claude.queries[1] == "Which project is late?"
    assert "Plan the site launch." in world.claude.queries[0]
    assert len({options.cwd for options in world.claude.options}) == 1


async def test_a_ceo_task_run_keeps_its_own_session(world: World) -> None:
    await _make_ceo(world)
    await _owner_turn(world, "Plan the site launch.")

    await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="Review")

    assert world.claude.options[1].resume is None
