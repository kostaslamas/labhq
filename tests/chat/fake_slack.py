"""A stateful stand-in for the Slack Web API and Socket Mode, so no test touches the network."""

import asyncio
import copy
import itertools
import json
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import BindingStore, Persona, Thread
from labhq.chat.base import ChatAdapter
from labhq.chat.contract import Speaker
from labhq.chat.slack import SlackAdapter, split_thread_id
from labhq.chat.slack_settings import SlackSettings
from labhq.chat.slack_socket import Envelope, SocketClosedError
from labhq.clock import Clock
from tests.chat.fake_discord import fixture

API = "https://slack.test/api"
SOCKET_URL = "wss://wss-primary.slack.test/link/?ticket=socket-ticket-secret&app_id=A0790000001"
OWNER_ID = "U0790000OWN"
BOT_TOKEN = "test-bot-token-SECRET-not-a-slack-token"
APP_TOKEN = "test-app-token-SECRET-not-a-slack-token"


def slack_settings(**overrides: object) -> SlackSettings:
    values: dict[str, object] = {
        "bot_token": BOT_TOKEN,
        "app_token": APP_TOKEN,
        "owner_id": OWNER_ID,
        "api_base": API,
    }
    return SlackSettings(**(values | overrides))  # type: ignore[arg-type]


class FakeSlackApi:
    """Answers the Web API methods the adapter calls, and records them."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.created = 0
        self.rate_limits: list[str] = []
        # Scripted failures for the next requests: an HTTP status, or an exception to raise.
        self.failures: list[int | Exception] = []
        self.channels: dict[str, str] = {}
        self.roots: dict[str, list[dict[str, Any]]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self._ids = itertools.count(1)
        self._methods: dict[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {
            "conversations.create": (BOT_TOKEN, self._create_channel),
            "chat.postMessage": (BOT_TOKEN, self._post_message),
            "apps.connections.open": (APP_TOKEN, lambda _body: {"url": SOCKET_URL}),
        }

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return httpx.Response(failure, text="failed")
        if self.rate_limits:
            return httpx.Response(
                429, headers={"Retry-After": self.rate_limits.pop(0)}, json={"ok": False}
            )
        method = request.url.path.removeprefix("/api/")
        if method not in self._methods:
            return httpx.Response(200, json={"ok": False, "error": "unknown_method"})
        token, handler = self._methods[method]
        if request.headers.get("Authorization") != f"Bearer {token}":
            return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
        try:
            answer = handler(json.loads(request.content))
        except LookupError as error:
            return httpx.Response(200, json={"ok": False, "error": str(error.args[0])})
        return httpx.Response(200, json={"ok": True, **answer})

    def calls(self, method: str) -> list[dict[str, Any]]:
        return [
            json.loads(request.content)
            for request in self.requests
            if request.url.path == f"/api/{method}"
        ]

    def _ts(self) -> str:
        return f"1727860000.{next(self._ids):06d}"

    def _create_channel(self, body: dict[str, Any]) -> dict[str, Any]:
        if body["name"] in self.channels.values():
            raise LookupError("name_taken")
        self.created += 1
        channel_id = f"C07A{next(self._ids):07d}"
        self.channels[channel_id] = body["name"]
        return {"channel": {"id": channel_id, "name": body["name"], "is_channel": True}}

    def _post_message(self, body: dict[str, Any]) -> dict[str, Any]:
        if body["channel"] not in self.channels:
            raise LookupError("channel_not_found")
        message = {**body, "ts": self._ts()}
        thread_ts = body.get("thread_ts")
        if thread_ts is None:
            self.roots.setdefault(body["channel"], []).append(message)
        else:
            self.messages.setdefault(f"{body['channel']}:{thread_ts}", []).append(message)
        return {"channel": body["channel"], "ts": message["ts"], "message": message}


class ScriptedSocket:
    """One Socket Mode connection: hello first, then whatever the test delivers."""

    def __init__(self, socket_mode: "ScriptedSocketMode", url: str) -> None:
        self.url = url
        self.sent: list[Envelope] = []
        self._socket_mode = socket_mode
        self._local: asyncio.Queue[Envelope] = asyncio.Queue()
        self._local.put_nowait(fixture("slack_hello"))
        self.closed = asyncio.Event()

    async def send(self, payload: Envelope) -> None:
        if self.closed.is_set():
            raise SocketClosedError
        self.sent.append(payload)

    async def receive(self) -> Envelope:
        if not self._local.empty():
            return self._local.get_nowait()
        event = asyncio.ensure_future(self._socket_mode.envelopes.get())
        closed = asyncio.ensure_future(self.closed.wait())
        await asyncio.wait({event, closed}, return_when=asyncio.FIRST_COMPLETED)
        event.cancel()
        closed.cancel()
        if self.closed.is_set():
            raise SocketClosedError
        return event.result()

    async def close(self) -> None:
        self.closed.set()


class ScriptedSocketMode:
    def __init__(self) -> None:
        self.envelopes: asyncio.Queue[Envelope] = asyncio.Queue()
        self.connections: list[ScriptedSocket] = []
        self._sequence = itertools.count(100)

    async def connect(self, url: str) -> ScriptedSocket:
        connection = ScriptedSocket(self, url)
        self.connections.append(connection)
        return connection

    def deliver(self, speaker: Speaker, where: str, text: str, **event: Any) -> Envelope:
        """An envelope from `speaker`: `where` is a thread id, or a channel id for top level."""
        envelope = copy.deepcopy(fixture(f"slack_message_{speaker}"))
        sequence = next(self._sequence)
        envelope["envelope_id"] = f"envelope-{sequence}"
        channel_id, thread_ts = split_thread_id(where)
        message = envelope["payload"]["event"]
        message.update(channel=channel_id, text=text, ts=f"1727861000.{sequence:06d}")
        message.update(event)
        if thread_ts:
            message["thread_ts"] = thread_ts
        else:
            del message["thread_ts"], message["parent_user_id"]
        self.envelopes.put_nowait(envelope)
        return envelope


class SlackHarness:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.api = FakeSlackApi()
        self.socket = ScriptedSocketMode()
        self.client = self.api.client()
        self._sessions = sessions
        self._clock = clock

    async def make(self) -> ChatAdapter:
        return self.adapter()

    def adapter(self, **overrides: object) -> SlackAdapter:
        return SlackAdapter(
            settings=slack_settings(**overrides),
            store=BindingStore(self._sessions, "slack", clock=self._clock),
            client=self.client,
            clock=self._clock,
            connect=self.socket.connect,
        )

    def created_objects(self) -> int:
        return self.api.created

    def posts(self, thread: Thread) -> list[tuple[Persona, str]]:
        return [
            (Persona(message["username"], message.get("icon_url")), message["text"])
            for message in self.api.messages.get(thread.id, [])
        ]

    async def say(self, channel_id: str, speaker: Speaker, text: str) -> None:
        self.socket.deliver(speaker, channel_id, text)
