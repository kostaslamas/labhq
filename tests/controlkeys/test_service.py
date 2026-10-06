"""Sending a named control key to a tmux agent: mapping, refusals and audit."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from labhq.adapters.tmux import default_kinds
from labhq.adapters.tmux.controlkeys import CONTROL_KEYS
from labhq.controlkeys import CONTROL_KEY_EVENT, OWNER_SENDER, ControlKeyError, agent_sender
from labhq.db.models import Agent, RunEvent
from tests.controlkeys.conftest import World


async def events(world: World, run: str) -> list[RunEvent]:
    async with world.sessions() as db:
        return list(
            await db.scalars(
                select(RunEvent).where(
                    RunEvent.run_id == world.runs[run], RunEvent.kind == CONTROL_KEY_EVENT
                )
            )
        )


async def test_owner_sends_escape_and_shift_tab_as_tmux_keys(world: World) -> None:
    await world.service.send(OWNER_SENDER, world.ids["worker_a"], "escape")
    await world.service.send(OWNER_SENDER, world.ids["worker_a"], "shift_tab")

    pane = world.pane("worker_a")
    assert world.panes.sent == [(pane, ("Escape",), False), (pane, ("BTab",), False)]


async def test_send_returns_the_screen_after_the_key(world: World) -> None:
    assert await world.service.send(OWNER_SENDER, world.ids["worker_a"], "shift_tab") == (
        "mode: auto-accept"
    )


@pytest.mark.parametrize("key", ["F1", "hello", "Escape", "BTab", "C-c", "escape\nrm -rf /", ""])
async def test_an_unlisted_name_or_literal_text_is_refused(world: World, key: str) -> None:
    with pytest.raises(ControlKeyError) as refused:
        await world.service.send(OWNER_SENDER, world.ids["worker_a"], key)

    assert refused.value.code == "key_refused"
    assert world.panes.sent == []


async def test_a_kind_that_does_not_list_a_key_refuses_it(world: World) -> None:
    # Aider reads Ctrl+C only.
    async with world.sessions() as db:
        agent = await db.get_one(Agent, world.ids["worker_a"])
        agent.config = {"agent": "aider"}
        await db.commit()

    with pytest.raises(ControlKeyError) as refused:
        await world.service.send(OWNER_SENDER, world.ids["worker_a"], "shift_tab")

    assert refused.value.code == "key_refused"
    assert world.panes.sent == []
    await world.service.send(OWNER_SENDER, world.ids["worker_a"], "ctrl_c")
    assert world.panes.sent[-1][1] == ("C-c",)


def test_every_listed_key_is_a_known_control_key() -> None:
    for name in default_kinds.names():
        assert set(default_kinds.get(name).control_keys) <= CONTROL_KEYS.keys()


async def test_an_sdk_agent_has_no_pane_to_send_to(world: World) -> None:
    with pytest.raises(ControlKeyError) as refused:
        await world.service.send(OWNER_SENDER, world.ids["sdk"], "escape")

    assert refused.value.code == "no_pane"
    assert "no live tmux pane" in str(refused.value)
    assert world.panes.sent == []
    assert (await world.service.support(world.ids["sdk"])).keys == []


@pytest.mark.parametrize("failure", ["dead", "gone"])
async def test_a_stopped_pane_is_refused(world: World, failure: str) -> None:
    getattr(world.panes, failure).add(world.pane("worker_a"))

    with pytest.raises(ControlKeyError) as refused:
        await world.service.send(OWNER_SENDER, world.ids["worker_a"], "escape")

    assert refused.value.code == "no_pane"
    assert await events(world, "worker_a") == []


async def test_support_lists_the_keys_of_the_agents_kind(world: World) -> None:
    support = await world.service.support(world.ids["worker_a"])

    assert support.live
    assert support.keys == ["escape", "shift_tab", "ctrl_c"]


async def test_every_key_sent_is_audited_with_sender_target_key_and_time(world: World) -> None:
    first = world.clock.now()
    await world.service.send(OWNER_SENDER, world.ids["worker_a"], "shift_tab")
    world.clock.advance(timedelta(seconds=5))
    await world.service.send(agent_sender(world.ids["manager_a"]), world.ids["lead_a"], "escape")

    (by_owner,) = await events(world, "worker_a")
    assert by_owner.payload == {
        "sender": "owner",
        "target": world.ids["worker_a"],
        "key": "shift_tab",
        "tmux_key": "BTab",
    }
    assert by_owner.created_at == first
    (by_agent,) = await events(world, "lead_a")
    assert by_agent.payload["sender"] == f"agent:{world.ids['manager_a']}"
    assert by_agent.created_at == first + timedelta(seconds=5)


async def test_a_refused_key_leaves_no_audit_row(world: World) -> None:
    with pytest.raises(ControlKeyError):
        await world.service.send(OWNER_SENDER, world.ids["worker_a"], "hello")

    assert await events(world, "worker_a") == []
