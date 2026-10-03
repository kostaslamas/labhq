"""Discord: a category, a channel per project, a public thread per meeting, one webhook each.

Posts go through the channel's webhook with a per-message `username` and `avatar_url`, so
each agent writes under its own name. The REST side is plain httpx; the gateway side is the
small client in `gateway.py`, both on libraries labhq already depends on.
"""

import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from labhq.chat.base import Channel, ChatError, Persona, Reply, Thread
from labhq.chat.bindings import BindingStore
from labhq.chat.discord.gateway import Gateway, GatewayConnector, Payload, websocket_connect
from labhq.chat.discord.rest import DiscordRest
from labhq.chat.discord.settings import DiscordSettings
from labhq.chat.text import split_message
from labhq.clock import Clock
from labhq.db.models.chat import ChatBindingKind

MESSAGE_LIMIT = 2000
GUILD_TEXT = 0
GUILD_CATEGORY = 4
PUBLIC_THREAD = 11
# A week, the longest Discord allows: a meeting thread stays open for follow-ups.
THREAD_ARCHIVE_MINUTES = 10080
WEBHOOK_NAME = "labhq"
VIEW_CHANNEL = 1 << 10
MANAGE_CHANNELS = 1 << 4
MANAGE_WEBHOOKS = 1 << 29
CREATE_PUBLIC_THREADS = 1 << 35
# Exactly what the calls below need; the invite link in docs/checks/discord.md grants this.
# Posting goes through webhooks, which need no send permission of the bot's own.
BOT_PERMISSIONS = VIEW_CHANNEL | MANAGE_CHANNELS | MANAGE_WEBHOOKS | CREATE_PUBLIC_THREADS
_NAME_LIMIT = 100
_USERNAME_LIMIT = 80
_CHANNEL_NAME_JUNK = re.compile(r"[^a-z0-9_-]+")


def channel_name(name: str) -> str:
    """Discord text channel names are lowercase with dashes; mirror what the client does."""
    slug = _CHANNEL_NAME_JUNK.sub("-", name.lower()).strip("-")
    return slug[:_NAME_LIMIT] or "project"


class DiscordAdapter:
    max_message_length = MESSAGE_LIMIT

    def __init__(
        self,
        *,
        settings: DiscordSettings,
        store: BindingStore,
        client: httpx.AsyncClient,
        clock: Clock,
        connect: GatewayConnector = websocket_connect,
    ) -> None:
        if settings.bot_token is None or not settings.guild_id or not settings.owner_id:
            raise ChatError(
                "discord needs LABHQ_DISCORD_BOT_TOKEN, LABHQ_DISCORD_GUILD_ID "
                "and LABHQ_DISCORD_OWNER_ID"
            )
        token = settings.bot_token.get_secret_value()
        self._settings = settings
        self._guild_id = settings.guild_id
        self._owner_id = settings.owner_id
        self._store = store
        self._rest = DiscordRest(
            client,
            token=token,
            api_base=settings.api_base,
            clock=clock,
            max_attempts=settings.max_attempts,
        )
        self._gateway = Gateway(
            token=token,
            locate=self._gateway_url,
            connect=connect,
            clock=clock,
            reconnect_seconds=settings.reconnect_seconds,
        )
        # Webhook tokens are credentials: held in memory for this process, never stored.
        self._webhook_tokens: dict[str, str] = {}

    async def ensure_channel(self, key: str, name: str) -> Channel:
        category_id = await self._store.ensure(
            ChatBindingKind.CATEGORY,
            self._settings.category_name,
            lambda: self._create_channel(self._settings.category_name, GUILD_CATEGORY),
        )
        channel_id = await self._store.ensure(
            ChatBindingKind.CHANNEL,
            key,
            lambda: self._create_channel(channel_name(name), GUILD_TEXT, parent_id=category_id),
        )
        await self._store.ensure(
            ChatBindingKind.WEBHOOK, key, lambda: self._create_webhook(channel_id)
        )
        return Channel(key, channel_id)

    async def open_thread(self, channel: Channel, title: str) -> Thread:
        created = await self._rest.call(
            "POST",
            f"/channels/{channel.id}/threads",
            json={
                "name": title[:_NAME_LIMIT] or "meeting",
                "type": PUBLIC_THREAD,
                "auto_archive_duration": THREAD_ARCHIVE_MINUTES,
            },
        )
        thread = Thread(channel, str(created["id"]))
        await self._store.bind_thread(thread)
        return thread

    async def post(self, thread: Thread, persona: Persona, text: str) -> list[str]:
        webhook_id = await self._store.external_id(ChatBindingKind.WEBHOOK, thread.channel.key)
        if webhook_id is None:
            raise ChatError(f"channel {thread.channel.key!r} has no webhook; ensure it first")
        token = await self._webhook_token(webhook_id)
        body: dict[str, Any] = {
            "username": persona.name[:_USERNAME_LIMIT],
            # Agents quote people and code; never let a post ping anyone.
            "allowed_mentions": {"parse": []},
        }
        if persona.avatar_url:
            body["avatar_url"] = persona.avatar_url
        refs = []
        for part in split_message(text, self.max_message_length):
            sent = await self._rest.call(
                "POST",
                f"/webhooks/{webhook_id}/{token}",
                json={**body, "content": part},
                params={"wait": "true", "thread_id": thread.id},
                bot_auth=False,
            )
            refs.append(str(sent["id"]))
        return refs

    async def replies(self) -> AsyncIterator[Reply]:
        async for message in self._gateway.messages():
            reply = await self._accept(message)
            if reply is not None:
                yield reply

    async def close(self) -> None:
        await self._gateway.close()

    async def _accept(self, message: Payload) -> Reply | None:
        author = message.get("author") or {}
        # The mirror's own webhook posts come back through the gateway; never echo them.
        if message.get("webhook_id") or author.get("bot"):
            return None
        if str(author.get("id")) != self._owner_id:
            return None
        thread = await self._store.labhq_thread(str(message.get("channel_id")))
        if thread is None:
            return None
        name = author.get("global_name") or author.get("username") or self._owner_id
        return Reply(thread, str(name), str(message.get("content", "")), str(message["id"]))

    async def _create_channel(self, name: str, kind: int, *, parent_id: str | None = None) -> str:
        body: dict[str, Any] = {"name": name, "type": kind}
        if parent_id is not None:
            body["parent_id"] = parent_id
        created = await self._rest.call("POST", f"/guilds/{self._guild_id}/channels", json=body)
        return str(created["id"])

    async def _create_webhook(self, channel_id: str) -> str:
        created = await self._rest.call(
            "POST", f"/channels/{channel_id}/webhooks", json={"name": WEBHOOK_NAME}
        )
        self._webhook_tokens[str(created["id"])] = str(created["token"])
        return str(created["id"])

    async def _webhook_token(self, webhook_id: str) -> str:
        if webhook_id not in self._webhook_tokens:
            fetched = await self._rest.call("GET", f"/webhooks/{webhook_id}")
            self._webhook_tokens[webhook_id] = str(fetched["token"])
        return self._webhook_tokens[webhook_id]

    async def _gateway_url(self) -> str:
        located = await self._rest.call("GET", "/gateway/bot")
        return str(located["url"])
