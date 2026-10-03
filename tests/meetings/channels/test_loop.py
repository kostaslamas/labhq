"""The program's `chat` loop: replies in, outbox out, through the configured adapter."""

import asyncio
from typing import Any

from sqlalchemy import select

from labhq.approvals.registry import Registry
from labhq.chat import ChatAdapterFactory
from labhq.chat.fake import FakeInbound
from labhq.db.enums import TranscriptSource
from labhq.db.models import MeetingTranscriptEntry
from labhq.meetings import MeetingEvent, add_owner_entry
from labhq.meetings.channels.loop import ChannelLoop, chat_step
from labhq.meetings.channels.settings import ChannelSettings
from labhq.program import ProgramSettings, default_loops
from tests.meetings.channels.conftest import ADAPTER, Bridge

# A bound on a hang, not a pace: each wait ends on an event.
WAIT_SECONDS = 10


def test_the_chat_loop_is_registered_in_the_program() -> None:
    (spec,) = [spec for spec in default_loops if spec.name == "chat"]
    assert spec.build is chat_step
    assert spec.interval(ProgramSettings()) == ProgramSettings().chat_interval_seconds


async def test_with_no_adapter_configured_a_pass_does_nothing(bridge: Bridge) -> None:
    world = bridge.world
    loop = ChannelLoop(
        world.sessions, world.clock, adapters=Registry[ChatAdapterFactory]("chat adapter")
    )

    assert loop.adapter_name() is None
    await loop.run()


async def test_a_chosen_adapter_that_is_not_configured_is_none(bridge: Bridge) -> None:
    world = bridge.world
    adapters = Registry[ChatAdapterFactory]("chat adapter")
    adapters.register(ADAPTER, lambda _context: bridge.adapter)

    chosen = ChannelLoop(
        world.sessions, world.clock, adapters=adapters, settings=ChannelSettings(adapter="slack")
    )

    assert chosen.adapter_name() is None


async def test_a_running_pass_posts_the_outbox_and_records_owner_replies(bridge: Bridge) -> None:
    world = bridge.world
    meeting = await world.service.request(project_id=world.project_id, kind="standup")
    await add_owner_entry(
        world.sessions,
        world.clock,
        meeting_id=meeting.id,
        text="agenda looks fine",
        listeners=world.listeners,
    )
    adapters = Registry[ChatAdapterFactory]("chat adapter")
    adapters.register(ADAPTER, lambda _context: bridge.adapter)
    loop = ChannelLoop(
        world.sessions,
        world.clock,
        adapters=adapters,
        settings=bridge.settings,
        listeners=world.listeners,
    )

    posted = asyncio.Event()
    replied = asyncio.Event()
    real_post = bridge.adapter.post

    async def post_and_tell(*args: Any) -> list[str]:
        refs = await real_post(*args)
        posted.set()
        return refs

    async def tell_reply(event: MeetingEvent) -> None:
        replied.set()

    bridge.adapter.post = post_and_tell  # type: ignore[method-assign]
    world.listeners.register("test", tell_reply)

    task = asyncio.create_task(loop.run())
    await asyncio.wait_for(posted.wait(), WAIT_SECONDS)
    thread = await bridge.thread_of(meeting.id)
    await bridge.service.inbound.put(FakeInbound(thread.id, "owner", "owner", "ship it"))
    await asyncio.wait_for(replied.wait(), WAIT_SECONDS)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert bridge.posts(thread.id) == [("Owner", "agenda looks fine")]
    async with world.sessions() as db:
        entries = list(await db.scalars(select(MeetingTranscriptEntry)))
    assert [(e.source, e.text, e.external_ref is None) for e in entries] == [
        (TranscriptSource.OWNER, "agenda looks fine", True),
        (TranscriptSource.OWNER, "ship it", False),
    ]
