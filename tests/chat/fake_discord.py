"""A stateful stand-in for the Discord REST API and gateway, so no test touches the network."""

import asyncio
import copy
import itertools
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from labhq.chat.contract import Speaker
from labhq.chat.discord.gateway import HEARTBEAT, HEARTBEAT_ACK, GatewayClosedError, Payload
from labhq.clock import FakeClock

FIXTURES = Path(__file__).parent / "fixtures"
API = "https://discord.test/api/v10"
GATEWAY_URL = "wss://gateway.discord.test"
GUILD_ID = "1280000000000000001"
OWNER_ID = "1270000000000000001"
BOT_TOKEN = "MTI5MDAwMDAwMDAwMDAwMDAwMQ.SECRET.bot-token-value"


def fixture(name: str) -> Payload:
    loaded: Payload = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return loaded


class FakeDiscordApi:
    """Answers the REST calls the adapter makes, and records them."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.created = 0
        self.rate_limits: list[float] = []
        # Scripted failures for the next requests: an HTTP status, or an exception to raise.
        self.failures: list[int | Exception] = []
        self.channels: dict[str, Payload] = {}
        self.webhook_tokens: dict[str, str] = {}
        self.messages: dict[str, list[Payload]] = {}
        self._ids = itertools.count(1300000000000000001)
        self._routes: list[tuple[str, re.Pattern[str], Callable[..., Payload]]] = [
            ("POST", re.compile(r"/guilds/\d+/channels"), self._create_channel),
            ("POST", re.compile(r"/channels/(\d+)/webhooks"), self._create_webhook),
            ("POST", re.compile(r"/channels/(\d+)/threads"), self._create_thread),
            ("GET", re.compile(r"/webhooks/(\d+)"), self._get_webhook),
            ("POST", re.compile(r"/webhooks/(\d+)/([^/]+)"), self._execute_webhook),
            ("GET", re.compile(r"/gateway/bot"), lambda _r: {"url": GATEWAY_URL}),
        ]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return httpx.Response(failure, json={"message": "failed", "code": 0})
        if self.rate_limits:
            wait = self.rate_limits.pop(0)
            return httpx.Response(429, json={"message": "rate limited", "retry_after": wait})
        path = request.url.path.removeprefix("/api/v10")
        for method, pattern, handler in self._routes:
            match = pattern.fullmatch(path)
            if request.method == method and match:
                return httpx.Response(200, json=handler(request, *match.groups()))
        return httpx.Response(404, json={"message": "Unknown route"})

    def calls(self, method: str, pattern: str) -> list[httpx.Request]:
        return [
            request
            for request in self.requests
            if request.method == method and re.fullmatch(pattern, request.url.path)
        ]

    def _new_id(self) -> str:
        return str(next(self._ids))

    def _create_channel(self, request: httpx.Request) -> Payload:
        self.created += 1
        channel = {"id": self._new_id(), **json.loads(request.content)}
        self.channels[channel["id"]] = channel
        return channel

    def _create_webhook(self, request: httpx.Request, channel_id: str) -> Payload:
        self.created += 1
        webhook_id = self._new_id()
        self.webhook_tokens[webhook_id] = f"webhook-token-{webhook_id}"
        return {
            "id": webhook_id,
            "channel_id": channel_id,
            "token": self.webhook_tokens[webhook_id],
        }

    def _create_thread(self, request: httpx.Request, channel_id: str) -> Payload:
        return {"id": self._new_id(), "parent_id": channel_id, **json.loads(request.content)}

    def _get_webhook(self, request: httpx.Request, webhook_id: str) -> Payload:
        return {"id": webhook_id, "token": self.webhook_tokens[webhook_id]}

    def _execute_webhook(self, request: httpx.Request, webhook_id: str, token: str) -> Payload:
        assert self.webhook_tokens[webhook_id] == token
        thread_id = request.url.params["thread_id"]
        message = {"id": self._new_id(), **json.loads(request.content)}
        self.messages.setdefault(thread_id, []).append(message)
        return message


class ScriptedConnection:
    """One gateway connection: hello and ready first, then whatever the test delivers."""

    def __init__(self, gateway: "ScriptedGateway", url: str) -> None:
        self.url = url
        self.sent: list[Payload] = []
        self._gateway = gateway
        self._local: asyncio.Queue[Payload] = asyncio.Queue()
        self._local.put_nowait(fixture("hello"))
        self._local.put_nowait(fixture("ready"))
        self._closed = asyncio.Event()
        self.close_code: int | None = 1000

    async def send(self, payload: Payload) -> None:
        if self._closed.is_set():
            raise GatewayClosedError(self.close_code)
        self.sent.append(payload)
        if payload["op"] == HEARTBEAT and self._gateway.ack_heartbeats:
            self._local.put_nowait({"op": HEARTBEAT_ACK, "d": None, "s": None, "t": None})

    async def receive(self) -> Payload:
        if not self._local.empty():
            return self._local.get_nowait()
        if self._closed.is_set():
            raise GatewayClosedError(self.close_code)
        event = asyncio.ensure_future(self._gateway.events.get())
        closed = asyncio.ensure_future(self._closed.wait())
        await asyncio.wait({event, closed}, return_when=asyncio.FIRST_COMPLETED)
        event.cancel()
        closed.cancel()
        if self._closed.is_set():
            raise GatewayClosedError(self.close_code)
        return event.result()

    async def close(self, code: int | None = 1000) -> None:
        self.close_code = code
        self._closed.set()


class ScriptedGateway:
    def __init__(self) -> None:
        self.events: asyncio.Queue[Payload] = asyncio.Queue()
        self.connections: list[ScriptedConnection] = []
        self.ack_heartbeats = True

    async def connect(self, url: str) -> ScriptedConnection:
        connection = ScriptedConnection(self, url)
        self.connections.append(connection)
        return connection

    def deliver(self, speaker: Speaker, channel_id: str, text: str, sequence: int = 20) -> None:
        event = copy.deepcopy(fixture(f"message_create_{speaker}"))
        event["s"] = sequence
        event["d"].update(channel_id=channel_id, content=text, id=f"{sequence}{channel_id}")
        self.events.put_nowait(event)


class SteppedClock(FakeClock):
    """A FakeClock whose `sleep` waits for the test to step it, so heartbeats never spin."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.sleeps: list[float] = []
        self._steps = asyncio.Semaphore(0)
        self._asleep = asyncio.Condition()

    async def sleep(self, seconds: float) -> None:
        async with self._asleep:
            self.sleeps.append(seconds)
            self._asleep.notify_all()
        await self._steps.acquire()
        self.advance(seconds)

    async def sleeping(self, count: int) -> None:
        """Wait until `count` sleeps have been requested in total."""
        async with self._asleep:
            await self._asleep.wait_for(lambda: len(self.sleeps) >= count)

    def step(self, count: int = 1) -> None:
        for _ in range(count):
            self._steps.release()
