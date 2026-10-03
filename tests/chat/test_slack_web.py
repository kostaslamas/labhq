"""Slack Web API: bindings across restarts, persona posts, long messages, rate limits."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import Channel, ChatError, Persona, Thread
from labhq.chat.slack import MESSAGE_LIMIT, channel_name
from labhq.chat.slack_api import SlackApiError
from labhq.clock import FakeClock
from labhq.db.models.chat import ChatBinding, ChatBindingKind
from tests.chat.fake_slack import SlackHarness


@pytest.fixture
async def slack(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> AsyncIterator[SlackHarness]:
    harness = SlackHarness(sessions, clock)
    async with harness.client:
        yield harness


async def test_a_project_channel_is_created_once_and_found_after_a_restart(
    slack: SlackHarness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    first = slack.adapter()
    channel = await first.ensure_channel("labhq-core", "LabHQ Core")
    assert await first.ensure_channel("labhq-core", "LabHQ Core") == channel
    await first.close()

    restarted = slack.adapter()
    assert await restarted.ensure_channel("labhq-core", "LabHQ Core") == channel
    thread = await restarted.open_thread(channel, "Standup")
    await restarted.post(thread, Persona("Alice"), "hi")

    assert slack.api.calls("conversations.create") == [{"name": "labhq-labhq-core"}]
    async with sessions() as db:
        rows = list(await db.scalars(select(ChatBinding).order_by(ChatBinding.id)))
    assert [(row.adapter, row.kind) for row in rows] == [
        ("slack", ChatBindingKind.CHANNEL),
        ("slack", ChatBindingKind.THREAD),
    ]
    assert rows[1].external_id == thread.id


async def test_a_thread_is_a_root_message_and_its_id_names_channel_and_ts(
    slack: SlackHarness,
) -> None:
    adapter = slack.adapter()
    channel = await adapter.ensure_channel("demo", "Demo")
    thread = await adapter.open_thread(channel, "Standup 2 Oct")
    (root,) = slack.api.roots[channel.id]
    assert root["text"] == "Standup 2 Oct" and "thread_ts" not in root
    assert thread.id == f"{channel.id}:{root['ts']}"


async def test_a_post_as_a_persona_sets_username_and_icon_url(slack: SlackHarness) -> None:
    adapter = slack.adapter()
    thread = await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Standup")
    await adapter.post(thread, Persona("Alice (PM)", "https://avatars.example/a.png"), "Hello")
    await adapter.post(thread, Persona("Bob"), "Hi")

    _, alice, bob = slack.api.calls("chat.postMessage")
    channel_id, ts = thread.id.split(":")
    assert alice == {
        "channel": channel_id,
        "thread_ts": ts,
        "username": "Alice (PM)",
        "icon_url": "https://avatars.example/a.png",
        "parse": "none",
        "link_names": False,
        "unfurl_links": False,
        "unfurl_media": False,
        "text": "Hello",
    }
    assert bob["username"] == "Bob" and "icon_url" not in bob


async def test_a_message_over_the_limit_arrives_as_ordered_parts_at_boundaries(
    slack: SlackHarness,
) -> None:
    adapter = slack.adapter()
    thread = await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Minutes")
    paragraph = "We keep one run per agent. The budget stays at 80%.\n" * 100
    text = paragraph + "Last line without a break"

    refs = await adapter.post(thread, Persona("Alice"), text)

    parts = [body for _, body in slack.posts(thread)]
    assert len(text) > MESSAGE_LIMIT and len(parts) == len(refs) == 2
    assert "".join(parts) == text
    assert all(len(part) <= MESSAGE_LIMIT for part in parts)
    assert parts[0].endswith(".\n")
    assert refs == sorted(refs)


async def test_a_429_is_retried_after_retry_after_on_the_fake_clock(
    slack: SlackHarness, clock: FakeClock
) -> None:
    adapter = slack.adapter()
    thread = await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Standup")
    before = clock.now()
    slack.api.rate_limits = ["3"]

    refs = await adapter.post(thread, Persona("Alice"), "Hello")

    assert len(refs) == 1
    assert (clock.now() - before).total_seconds() == 3
    assert len(slack.api.calls("chat.postMessage")) == 3  # the root, the 429, the retry
    assert slack.posts(thread) == [(Persona("Alice"), "Hello")]


async def test_rate_limits_beyond_the_attempt_budget_raise(slack: SlackHarness) -> None:
    adapter = slack.adapter(max_attempts=2)
    slack.api.rate_limits = ["1", "1"]
    with pytest.raises(ChatError, match="still rate limited after 2 attempts"):
        await adapter.ensure_channel("demo", "Demo")


async def test_a_refusal_raises_with_slacks_error_code(slack: SlackHarness) -> None:
    adapter = slack.adapter()
    with pytest.raises(SlackApiError, match="channel_not_found"):
        await adapter.open_thread(Channel("ghost", "C000"), "Standup")
    with pytest.raises(ChatError, match="HTTP 500"):
        slack.api.failures = [500]
        await adapter.post(Thread(Channel("ghost", "C000"), "C000:1.2"), Persona("A"), "hi")


async def test_an_unbound_channel_with_the_same_name_is_reported_not_adopted(
    slack: SlackHarness,
) -> None:
    slack.api.channels["C0700000999"] = "labhq-demo"
    adapter = slack.adapter()
    with pytest.raises(ChatError, match="LABHQ_SLACK_CHANNEL_PREFIX"):
        await adapter.ensure_channel("demo", "Demo")


def test_channel_names_follow_slack_rules() -> None:
    assert channel_name("labhq-", "LabHQ Core / v1.2!") == "labhq-labhq-core-v1-2"
    assert len(channel_name("labhq-", "x" * 200)) == 80
    assert channel_name("", "!!!") == "labhq"


@pytest.mark.parametrize("missing", ["app_token", "owner_id"])
def test_an_incomplete_configuration_is_refused(slack: SlackHarness, missing: str) -> None:
    with pytest.raises(ChatError, match="LABHQ_SLACK_OWNER_ID"):
        slack.adapter(**{missing: None})
