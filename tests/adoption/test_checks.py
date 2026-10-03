"""The engine checks the adopted manager: rules after compaction, status requests, checkout
changes and the plan cap."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from labhq.adoption import CHECKOUT_CHANGED, STATUS_REQUEST, rules_message, state_of
from labhq.adoption.session import send_message, session_name
from labhq.db.models import Agent, Notification, UsageReading
from tests.adoption.conftest import CLOCK, World, adopt, wait_for

pytestmark = pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")


async def turn(world: World, name: str, text: str) -> None:
    """Type `text` into the adopted agent and wait for the turn it causes to end."""
    count = world.inbox.count(text)
    send_message(world.private, name, text)
    await wait_for(lambda: world.inbox.count(text) > count, f"the agent to read {text!r}")
    await wait_for(lambda: turn_ended(world, name), "the turn to end")


def turn_ended(world: World, name: str) -> bool:
    # The signal file is rewritten at every turn end; wait until it is newer than the inbox.
    signal = world.private.state_dir / "adopted" / name / "turn-end.json"
    inbox = world.store / "inbox.log"
    return signal.exists() and signal.stat().st_mtime_ns >= inbox.stat().st_mtime_ns


async def settled(world: World, name: str) -> None:
    await wait_for(lambda: rules_message() in world.inbox, "the first rules message")
    await wait_for(lambda: turn_ended(world, name), "the rules turn to end")


async def test_first_message_rules_go_after_the_move_and_again_after_compaction(
    world: World,
) -> None:
    original, agent_id = await adopt(world)
    name = session_name(original.pid)
    await settled(world, name)
    assert world.inbox.count(rules_message()) == 1

    await turn(world, name, "/compact")
    report = await world.checks.check(agent_id)

    assert report.rules_sent
    await wait_for(lambda: world.inbox.count(rules_message()) == 2, "the rules again")


async def test_a_new_session_gets_the_rules_again(world: World) -> None:
    original, agent_id = await adopt(world)
    name = session_name(original.pid)
    await settled(world, name)
    await world.checks.check(agent_id)

    await turn(world, name, "/new")
    report = await world.checks.check(agent_id)

    assert report.rules_sent
    new_session = (world.store / "session").read_text(encoding="utf-8")
    async with world.sessions() as db:
        state = state_of(await db.get_one(Agent, agent_id))
    assert state is not None and state.session_id == new_session


async def test_a_turn_without_a_status_update_gets_one_request(world: World) -> None:
    original, agent_id = await adopt(world)
    name = session_name(original.pid)
    await settled(world, name)
    await world.checks.check(agent_id)

    await turn(world, name, "hello")
    first = await world.checks.check(agent_id)
    await wait_for(lambda: STATUS_REQUEST in world.inbox, "the status request")
    await wait_for(lambda: turn_ended(world, name), "the reply turn")
    second = await world.checks.check(agent_id)
    await turn(world, name, "STATUS")
    third = await world.checks.check(agent_id)

    assert first.turn_ended and first.status_requested
    assert second.turn_ended and not second.status_requested
    assert world.inbox.count(STATUS_REQUEST) == 1
    assert third.status_updated


async def test_a_change_in_the_main_checkout_notifies_the_owner(world: World) -> None:
    _, agent_id = await adopt(world)
    quiet = await world.checks.check(agent_id)

    (world.repo / "edited-after-the-move.txt").write_text("change\n", encoding="utf-8")
    changed = await world.checks.check(agent_id)
    again = await world.checks.check(agent_id)

    assert not quiet.checkout_changed
    assert changed.checkout_changed
    assert not again.checkout_changed
    async with world.sessions() as db:
        notes = list(
            await db.scalars(select(Notification).where(Notification.kind == CHECKOUT_CHANGED))
        )
    assert len(notes) == 1
    assert "edited-after-the-move.txt" in notes[0].body


async def test_at_the_plan_stop_percentage_labhq_holds_its_messages(world: World) -> None:
    original, agent_id = await adopt(world)
    name = session_name(original.pid)
    await settled(world, name)
    await world.checks.check(agent_id)
    resets = int((CLOCK.now() + timedelta(hours=2)).timestamp())
    document = {"rate_limits": {"five_hour": {"used_percentage": 75, "resets_at": resets}}}
    statusline = world.private.state_dir / "adopted" / name / "statusline.json"
    statusline.write_text(json.dumps(document), encoding="utf-8")

    await turn(world, name, "hello")
    report = await world.checks.check(agent_id)

    assert report.turn_ended and report.held
    assert STATUS_REQUEST not in world.inbox
    async with world.sessions() as db:
        readings = list(await db.scalars(select(UsageReading)))
        plan = list(await db.scalars(select(Notification).where(Notification.kind == "plan_usage")))
    assert [(r.window, r.value) for r in readings] == [("five_hour", 75.0)]
    assert plan
