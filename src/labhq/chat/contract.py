"""The behaviour every chat adapter must show, as checks that run against a harness.

CI runs these against the fake, against the Discord adapter with its REST API mocked and its
gateway fed from fixtures, and against the Slack adapter with its Web API mocked and its
Socket Mode events fed from fixtures. A harness wraps one adapter together with a scripted
remote side.
"""

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol

from labhq.chat.base import ChatAdapter, Persona, Thread

LONG_MESSAGE_LENGTH = 4500
ALICE = Persona("Alice (PM)", "https://avatars.example/alice.png")
BOB = Persona("Bob (worker)", None)


class ContractViolationError(AssertionError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractViolationError(message)


class Speaker(StrEnum):
    OWNER = "owner"
    OTHER_USER = "other_user"
    BOT = "bot"
    WEBHOOK = "webhook"


class ChatHarness(Protocol):
    async def make(self) -> ChatAdapter:
        """A new adapter over the same remote and database, as after a restart."""
        ...

    def created_objects(self) -> int:
        """How many channels, categories and webhooks the remote side has created."""
        ...

    def posts(self, thread: Thread) -> list[tuple[Persona, str]]:
        """What the remote side received in `thread`, in order."""
        ...

    async def say(self, channel_id: str, speaker: Speaker, text: str) -> None:
        """Make the remote side deliver an inbound message."""
        ...


def long_message(limit: int = 2000) -> str:
    """A message that splits into at least three parts at `limit` (4500 characters at 2000)."""
    length = LONG_MESSAGE_LENGTH * limit // 2000
    sentence = "Decision {n}: the scheduler keeps one run per agent. "
    count = length // 200 + 1
    lines = ["".join(sentence.format(n=f"{line}.{n}") for n in range(4)) for line in range(count)]
    return "\n".join(lines)[:length]


async def check_channel_survives_restart(harness: ChatHarness) -> None:
    first = await harness.make()
    channel = await first.ensure_channel("demo", "Demo")
    require(
        await first.ensure_channel("demo", "Demo") == channel, "a second call made a new channel"
    )
    created = harness.created_objects()
    await first.close()

    again = await harness.make()
    require(await again.ensure_channel("demo", "Demo") == channel, "the restart lost the channel")
    thread = await again.open_thread(channel, "Standup")
    await again.post(thread, ALICE, "after restart")
    require(harness.created_objects() == created, "the restart created remote objects again")
    await again.close()


async def check_posts_as_persona(harness: ChatHarness) -> None:
    adapter = await harness.make()
    channel = await adapter.ensure_channel("demo", "Demo")
    thread = await adapter.open_thread(channel, "Standup")
    refs = await adapter.post(thread, ALICE, "Good morning")
    refs += await adapter.post(thread, BOB, "Morning")
    require(len(refs) == 2, f"two short posts gave {len(refs)} refs")
    require(
        harness.posts(thread) == [(ALICE, "Good morning"), (BOB, "Morning")],
        f"posts arrived as {harness.posts(thread)!r}",
    )
    await adapter.close()


async def check_long_message_is_split_in_order(harness: ChatHarness) -> None:
    adapter = await harness.make()
    thread = await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Minutes")
    # Scaled to the adapter's limit: a fixed length only splits three ways under Discord's.
    text = long_message(adapter.max_message_length)
    refs = await adapter.post(thread, ALICE, text)
    parts = [body for _, body in harness.posts(thread)]
    require(len(refs) == len(parts) >= 3, f"{len(text)} characters arrived as {len(parts)}")
    require("".join(parts) == text, "the parts do not reassemble the message in order")
    limit = adapter.max_message_length
    require(all(len(part) <= limit for part in parts), f"a part is over {limit} characters")
    require(all(part[-1].isspace() for part in parts[:-1]), "a part was cut inside a word")
    await adapter.close()


async def check_only_owner_replies_in_labhq_threads(harness: ChatHarness) -> None:
    adapter = await harness.make()
    channel = await adapter.ensure_channel("demo", "Demo")
    thread = await adapter.open_thread(channel, "Standup")
    replies = adapter.replies()
    for speaker in (Speaker.BOT, Speaker.WEBHOOK, Speaker.OTHER_USER):
        await harness.say(thread.id, speaker, f"from {speaker}")
    await harness.say(channel.id, Speaker.OWNER, "outside any thread")
    await harness.say("999999", Speaker.OWNER, "in a thread labhq did not open")
    await harness.say(thread.id, Speaker.OWNER, "ship it")

    reply = await anext(replies)
    require(reply.thread == thread, f"the reply names {reply.thread!r}")
    require(reply.text == "ship it", f"the first reply yielded was {reply.text!r}")
    require(bool(reply.ref) and bool(reply.author), "the reply has no ref or author")
    await adapter.close()
    rest = [late async for late in replies]
    require(rest == [], f"after close the adapter still yielded {rest!r}")


Check = Callable[[ChatHarness], Awaitable[None]]

CHECKS: dict[str, Check] = {
    "channel_survives_restart": check_channel_survives_restart,
    "posts_as_persona": check_posts_as_persona,
    "long_message_is_split_in_order": check_long_message_is_split_in_order,
    "only_owner_replies_in_labhq_threads": check_only_owner_replies_in_labhq_threads,
}
