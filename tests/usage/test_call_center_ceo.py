"""What the Call Center sends reaches the CEO's run byte for byte, and a limited primary hands
the message to the backup exactly as a web chat message (issue #167)."""

from datetime import timedelta

from sqlalchemy import select

from labhq.callcenter.calls import confirm_wording, propose_wording, send_request
from labhq.ceochat_retry import retry_limited_messages
from labhq.db.enums import RunStatus
from labhq.db.models import Run, WordingProposal
from labhq.memory import memory_preamble
from labhq.memory.settings import MemorySettings
from tests.callcenter.factories import open_call, owner_request
from tests.scheduler.conftest import World
from tests.scheduler.helpers import set_agent
from tests.usage.plan_world import PLAN, add_reading, on_kind

# Odd spacing and a stray quote stay: the CEO gets what was agreed, not a tidied copy.
SPOKEN = 'uh  tell the team to ship the "login" form\nby friday'
CLEARER = "Ship the login form by Friday.  Ask the team for a demo."


def ceo_prompt(agreed: str) -> str:
    """The CEO's own memory section, as every run of it starts, then the agreed text alone."""
    return f"{memory_preamble('', 0, MemorySettings())}\n\n{agreed}"


async def make_ceo(world: World) -> None:
    await set_agent(world, role="ceo", project_id=None)


async def a_call(world: World, *requests: tuple[str, str]) -> int:
    async with world.sessions() as db:
        call = await open_call(db, world.clock)
        for request_id, text in requests:
            await owner_request(db, world.clock, call.id, request_id, text)
        await db.commit()
        return call.id


async def test_the_owners_words_follow_only_the_ceos_own_memory(world: World) -> None:
    await make_ceo(world)
    call_id = await a_call(world, ("r1", SPOKEN))
    async with world.sessions() as db:
        await send_request(db, world.clock, call_id=call_id, request_id="r1")

    report = await world.scheduler.tick()
    await world.scheduler.settle()

    assert len(report.started) == 1
    assert world.fake.requests[-1].prompt == ceo_prompt(SPOKEN)


async def test_a_confirmed_wording_follows_only_the_ceos_own_memory(world: World) -> None:
    await make_ceo(world)
    call_id = await a_call(world, ("r1", SPOKEN))
    async with world.sessions() as db:
        await propose_wording(db, world.clock, call_id=call_id, request_id="r1", text=CLEARER)
        proposal_id = await db.scalar(select(WordingProposal.id))
        assert proposal_id is not None
        assert (await world.scheduler.tick()).started == []
        await owner_request(db, world.clock, call_id, "r2", "Yes.")
        await db.commit()
        await confirm_wording(
            db, world.clock, call_id=call_id, proposal_id=proposal_id, request_id="r2"
        )

    await world.scheduler.tick()
    await world.scheduler.settle()

    assert [request.prompt for request in world.fake.requests] == [ceo_prompt(CLEARER)]


async def test_a_limited_primary_retries_the_message_on_the_backup(world: World) -> None:
    scheduler = await on_kind(world, {"agent": "fake-a", "fallback_agent": "fake-b"})
    await make_ceo(world)
    call_id = await a_call(world, ("r1", SPOKEN))
    async with world.sessions() as db:
        await send_request(db, world.clock, call_id=call_id, request_id="r1")
    world.fake.fail_with = RuntimeError("usage limit reached")
    (first_run,) = (await scheduler.tick()).started
    await scheduler.settle()
    async with world.sessions() as db:
        assert (await db.get_one(Run, first_run)).status is RunStatus.FAILED
    await add_reading(world, "fake-a", 100, resets_at=world.clock.now() + timedelta(hours=1))

    retried = await retry_limited_messages(world.sessions, world.clock, [first_run], PLAN)
    world.fake.fail_with = None
    report = await scheduler.tick()
    await scheduler.settle()

    assert len(retried) == 1
    assert len(report.started) == 1
    backup = world.fake.requests[-1]
    assert backup.config["agent"] == "fake-b"
    assert backup.prompt == ceo_prompt(SPOKEN)
