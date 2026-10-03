"""Discord REST: bindings across restarts, persona posts, rate limits."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import Channel, ChatError, Persona, Thread
from labhq.chat.discord.adapter import GUILD_CATEGORY, GUILD_TEXT, PUBLIC_THREAD, channel_name
from labhq.clock import FakeClock
from labhq.db.models.chat import ChatBinding, ChatBindingKind
from tests.chat.conftest import DiscordHarness

CHANNELS = r"/api/v10/guilds/\d+/channels"
WEBHOOKS = r"/api/v10/channels/\d+/webhooks"
EXECUTE = r"/api/v10/webhooks/\d+/[^/]+"


@pytest.fixture
async def discord(sessions: async_sessionmaker[AsyncSession], clock: FakeClock):  # type: ignore[no-untyped-def]
    harness = DiscordHarness(sessions, clock)
    async with harness.client:
        yield harness


async def test_project_channel_and_webhook_are_created_once_and_found_after_restart(
    discord: DiscordHarness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    first = discord.adapter()
    channel = await first.ensure_channel("labhq-core", "LabHQ Core")
    await first.ensure_channel("labhq-core", "LabHQ Core")
    await first.close()

    restarted = discord.adapter()
    assert await restarted.ensure_channel("labhq-core", "LabHQ Core") == channel
    thread = await restarted.open_thread(channel, "Standup")
    await restarted.post(thread, Persona("Alice"), "hi")

    category, project = (json.loads(r.content) for r in discord.api.calls("POST", CHANNELS))
    assert category == {"name": "labhq", "type": GUILD_CATEGORY}
    assert project["type"] == GUILD_TEXT and project["name"] == "labhq-core"
    assert len(discord.api.calls("POST", WEBHOOKS)) == 1
    # The restarted process never saw the token: it asks the API for it, once.
    assert len(discord.api.calls("GET", r"/api/v10/webhooks/\d+")) == 1

    async with sessions() as db:
        rows = list(await db.scalars(select(ChatBinding).order_by(ChatBinding.id)))
    assert [row.kind for row in rows] == [
        ChatBindingKind.CATEGORY,
        ChatBindingKind.CHANNEL,
        ChatBindingKind.WEBHOOK,
        ChatBindingKind.THREAD,
    ]
    tokens = discord.api.webhook_tokens.values()
    assert not any(token in (row.local_key, row.external_id) for row in rows for token in tokens)


async def test_a_post_sets_the_webhook_username_and_avatar_per_message(
    discord: DiscordHarness,
) -> None:
    adapter = discord.adapter()
    thread = await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Standup")
    await adapter.post(thread, Persona("Alice (PM)", "https://avatars.example/a.png"), "Hello")
    await adapter.post(thread, Persona("Bob"), "Hi")

    alice, bob = discord.api.calls("POST", EXECUTE)
    assert json.loads(alice.content) == {
        "username": "Alice (PM)",
        "avatar_url": "https://avatars.example/a.png",
        "allowed_mentions": {"parse": []},
        "content": "Hello",
    }
    assert json.loads(bob.content)["username"] == "Bob"
    assert "avatar_url" not in json.loads(bob.content)
    assert dict(alice.url.params) == {"wait": "true", "thread_id": thread.id}
    # The webhook path carries its own token; the bot token is not sent along.
    assert "Authorization" not in alice.headers


async def test_a_thread_is_public_and_titled(discord: DiscordHarness) -> None:
    adapter = discord.adapter()
    await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Standup 2 Oct")
    (request,) = discord.api.calls("POST", r"/api/v10/channels/\d+/threads")
    body = json.loads(request.content)
    assert (body["name"], body["type"]) == ("Standup 2 Oct", PUBLIC_THREAD)


async def test_a_429_is_retried_after_retry_after_on_the_fake_clock(
    discord: DiscordHarness, clock: FakeClock
) -> None:
    adapter = discord.adapter()
    thread = await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Standup")
    before = clock.now()
    discord.api.rate_limits = [2.5]

    refs = await adapter.post(thread, Persona("Alice"), "Hello")

    assert len(refs) == 1
    assert (clock.now() - before).total_seconds() == 2.5
    assert len(discord.api.calls("POST", EXECUTE)) == 2
    assert discord.posts(thread) == [(Persona("Alice"), "Hello")]


async def test_rate_limits_beyond_the_attempt_budget_raise(
    discord: DiscordHarness, clock: FakeClock
) -> None:
    adapter = discord.adapter(max_attempts=3)
    discord.api.rate_limits = [1.0, 1.0, 1.0]
    with pytest.raises(ChatError, match="still rate limited after 3 attempts"):
        await adapter.ensure_channel("demo", "Demo")


async def test_post_into_a_channel_never_ensured_is_refused(discord: DiscordHarness) -> None:
    adapter = discord.adapter()
    with pytest.raises(ChatError, match="ensure it first"):
        await adapter.post(Thread(Channel("ghost", "1"), "2"), Persona("Alice"), "hi")


def test_channel_names_follow_discord_rules() -> None:
    assert channel_name("LabHQ Core / Web!") == "labhq-core-web"
    assert channel_name("!!!") == "project"


@pytest.mark.parametrize("missing", ["guild_id", "owner_id"])
def test_a_token_without_guild_or_owner_is_refused(discord: DiscordHarness, missing: str) -> None:
    with pytest.raises(ChatError, match="LABHQ_DISCORD_GUILD_ID"):
        discord.adapter(**{missing: None})
