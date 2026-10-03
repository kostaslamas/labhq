"""Slack: a public channel per project, a thread per meeting, persona posts, Socket Mode in.

Posts go through `chat.postMessage` with a per-message `username` and `icon_url`
(`chat:write.customize`), so each agent writes under its own name. Inbound messages arrive
over Socket Mode, so no public URL is needed. Both sides are plain httpx and websockets,
which labhq already depends on; `slack_sdk` would add a dependency for four calls.
"""

import re
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

import httpx

from labhq.chat.base import Channel, ChatError, Persona, Reply, Thread
from labhq.chat.bindings import BindingStore
from labhq.chat.slack_api import SlackApi, SlackApiError
from labhq.chat.slack_settings import SlackSettings
from labhq.chat.slack_socket import SocketConnector, SocketMode, websocket_connect
from labhq.chat.text import split_message
from labhq.clock import Clock
from labhq.db.models.chat import ChatBindingKind

# Slack accepts far longer `text`, but asks to keep it under 4000 characters for display.
MESSAGE_LIMIT = 4000
# Exactly the bot scopes the calls below need; docs/guide/slack-manifest.yaml grants these.
BOT_SCOPES = frozenset(
    {"channels:manage", "channels:history", "chat:write", "chat:write.customize"}
)
# The app-level token needs this one to open Socket Mode.
APP_SCOPES = frozenset({"connections:write"})
BOT_EVENTS = frozenset({"message.channels"})
_NAME_LIMIT = 80
_USERNAME_LIMIT = 80
_CHANNEL_NAME_JUNK = re.compile(r"[^a-z0-9_-]+")
# Slack redelivers an envelope it thinks was lost; remember enough messages to drop repeats.
_SEEN_LIMIT = 512
# A reply also sent to the channel is still the owner's reply; every other subtype
# (bot_message, message_changed, channel_join, ...) is not.
_REPLY_SUBTYPES = frozenset({None, "thread_broadcast"})


def channel_name(prefix: str, name: str) -> str:
    """Slack channel names are lowercase, without spaces or periods, at most 80 characters."""
    slug = _CHANNEL_NAME_JUNK.sub("-", f"{prefix}{name}".lower()).strip("-")
    return slug[:_NAME_LIMIT] or "labhq"


def thread_id(channel_id: str, ts: str) -> str:
    # A `ts` is unique only within its channel, so the thread id names both.
    return f"{channel_id}:{ts}"


def split_thread_id(value: str) -> tuple[str, str]:
    channel_id, _, ts = value.partition(":")
    return channel_id, ts


class SlackAdapter:
    max_message_length = MESSAGE_LIMIT

    def __init__(
        self,
        *,
        settings: SlackSettings,
        store: BindingStore,
        client: httpx.AsyncClient,
        clock: Clock,
        connect: SocketConnector = websocket_connect,
    ) -> None:
        if settings.bot_token is None or settings.app_token is None or not settings.owner_id:
            raise ChatError(
                "slack needs LABHQ_SLACK_BOT_TOKEN, LABHQ_SLACK_APP_TOKEN and LABHQ_SLACK_OWNER_ID"
            )
        self._bot_token = settings.bot_token
        self._app_token = settings.app_token
        self._owner_id = settings.owner_id
        self._prefix = settings.channel_prefix
        self._store = store
        self._api = SlackApi(
            client, api_base=settings.api_base, clock=clock, max_attempts=settings.max_attempts
        )
        self._socket = SocketMode(
            locate=self._socket_url,
            connect=connect,
            clock=clock,
            reconnect_seconds=settings.reconnect_seconds,
        )
        self._seen: OrderedDict[str, None] = OrderedDict()

    def __repr__(self) -> str:
        return f"SlackAdapter(owner_id={self._owner_id!r})"

    async def ensure_channel(self, key: str, name: str) -> Channel:
        channel_id = await self._store.ensure(
            ChatBindingKind.CHANNEL, key, lambda: self._create_channel(name)
        )
        return Channel(key, channel_id)

    async def open_thread(self, channel: Channel, title: str) -> Thread:
        # Slack has no thread object: a thread is the replies to a root message.
        root = await self._web(
            "chat.postMessage", {"channel": channel.id, "text": title or "meeting"}
        )
        thread = Thread(channel, thread_id(channel.id, str(root["ts"])))
        await self._store.bind_thread(thread)
        return thread

    async def post(self, thread: Thread, persona: Persona, text: str) -> list[str]:
        channel_id, ts = split_thread_id(thread.id)
        body: dict[str, Any] = {
            "channel": channel_id,
            "thread_ts": ts,
            "username": persona.name[:_USERNAME_LIMIT],
            # Agents quote people and links; never let a post ping anyone or unfurl.
            "parse": "none",
            "link_names": False,
            "unfurl_links": False,
            "unfurl_media": False,
        }
        if persona.avatar_url:
            body["icon_url"] = persona.avatar_url
        refs = []
        for part in split_message(text, self.max_message_length):
            sent = await self._web("chat.postMessage", {**body, "text": part})
            refs.append(str(sent["ts"]))
        return refs

    async def replies(self) -> AsyncIterator[Reply]:
        async for event in self._socket.events():
            reply = await self._accept(event)
            if reply is not None:
                yield reply

    async def close(self) -> None:
        await self._socket.close()

    async def _accept(self, event: dict[str, Any]) -> Reply | None:
        if event.get("type") != "message":
            return None
        # The mirror's own posts and other apps' come back as messages; never echo them.
        if event.get("bot_id") or event.get("app_id"):
            return None
        if event.get("subtype") not in _REPLY_SUBTYPES:
            return None
        if event.get("user") != self._owner_id or not event.get("thread_ts"):
            return None
        if not self._first_sight(f"{event.get('channel')}:{event.get('ts')}"):
            return None
        thread = await self._store.labhq_thread(
            thread_id(str(event.get("channel")), str(event["thread_ts"]))
        )
        if thread is None:
            return None
        return Reply(thread, self._owner_id, str(event.get("text", "")), str(event.get("ts")))

    def _first_sight(self, message: str) -> bool:
        if message in self._seen:
            return False
        self._seen[message] = None
        if len(self._seen) > _SEEN_LIMIT:
            self._seen.popitem(last=False)
        return True

    async def _create_channel(self, name: str) -> str:
        wanted = channel_name(self._prefix, name)
        try:
            created = await self._web("conversations.create", {"name": wanted})
        except SlackApiError as error:
            if error.error == "name_taken":
                raise ChatError(
                    f"slack channel #{wanted} exists but labhq has no binding for it; "
                    "rename or archive it, or change LABHQ_SLACK_CHANNEL_PREFIX"
                ) from None
            raise
        return str(created["channel"]["id"])

    async def _web(self, method: str, body: dict[str, Any]) -> Any:
        return await self._api.call(method, self._bot_token.get_secret_value(), body)

    async def _socket_url(self) -> str:
        opened = await self._api.call("apps.connections.open", self._app_token.get_secret_value())
        return str(opened["url"])
