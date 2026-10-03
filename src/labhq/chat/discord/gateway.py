"""A minimal Discord gateway client: identify, heartbeat, reconnect, yield new messages.

Only `MESSAGE_CREATE` matters to labhq, so there is no resume and no cache: after any drop
the client identifies again, and messages sent while it was away are not replayed.
"""

import asyncio
import contextlib
import json
import logging
import random
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from labhq.chat.base import ChatError
from labhq.clock import Clock

GUILDS = 1 << 0
GUILD_MESSAGES = 1 << 9
MESSAGE_CONTENT = 1 << 15
INTENTS = GUILDS | GUILD_MESSAGES | MESSAGE_CONTENT

DISPATCH = 0
HEARTBEAT = 1
IDENTIFY = 2
RECONNECT = 7
INVALID_SESSION = 9
HELLO = 10
HEARTBEAT_ACK = 11

# Retrying these cannot succeed: a bad token, a bad shard or an intent not enabled.
FATAL_CLOSE_CODES = frozenset({4004, 4010, 4011, 4012, 4013, 4014})

# websockets logs frame contents at DEBUG, and the identify frame carries the bot token. A
# dedicated logger with its own level keeps those lines out even under a global DEBUG.
_SOCKET_LOGGER = logging.getLogger("labhq.chat.discord.websocket")
_SOCKET_LOGGER.setLevel(logging.INFO)

type Payload = dict[str, Any]


class GatewayClosedError(Exception):
    def __init__(self, code: int | None) -> None:
        super().__init__(f"gateway closed with code {code}")
        self.code = code


class GatewayConnection(Protocol):
    async def send(self, payload: Payload) -> None: ...

    async def receive(self) -> Payload:
        """The next event; raises `GatewayClosedError` once the connection is gone."""
        ...

    async def close(self) -> None: ...


type GatewayConnector = Callable[[str], Awaitable[GatewayConnection]]


class _WebSocketConnection:
    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket

    async def send(self, payload: Payload) -> None:
        try:
            await self._socket.send(json.dumps(payload))
        except ConnectionClosed as closed:
            raise GatewayClosedError(closed.rcvd.code if closed.rcvd else None) from None

    async def receive(self) -> Payload:
        try:
            raw = await self._socket.recv()
        except ConnectionClosed as closed:
            raise GatewayClosedError(closed.rcvd.code if closed.rcvd else None) from None
        event: Payload = json.loads(raw)
        return event

    async def close(self) -> None:
        await self._socket.close()


async def websocket_connect(url: str) -> GatewayConnection:
    return _WebSocketConnection(await connect(url, logger=_SOCKET_LOGGER))


class Gateway:
    def __init__(
        self,
        *,
        token: str,
        locate: Callable[[], Awaitable[str]],
        connect: GatewayConnector,
        clock: Clock,
        reconnect_seconds: float,
    ) -> None:
        self._token = token
        self._locate = locate
        self._connect = connect
        self._clock = clock
        self._reconnect_seconds = reconnect_seconds
        self._sequence: int | None = None
        self._acked = True
        self._connection: GatewayConnection | None = None
        self._closed = asyncio.Event()

    async def messages(self) -> AsyncIterator[Payload]:
        """Every `MESSAGE_CREATE` payload, across reconnects, until `close`."""
        while not self._closed.is_set():
            try:
                async for message in self._session():
                    yield message
            except GatewayClosedError as closed:
                if self._closed.is_set():
                    return
                if closed.code in FATAL_CLOSE_CODES:
                    raise ChatError(
                        f"discord gateway refused the bot: code {closed.code}"
                    ) from None
            if not self._closed.is_set():
                await self._clock.sleep(self._reconnect_seconds)

    async def close(self) -> None:
        self._closed.set()
        if self._connection is not None:
            await self._connection.close()

    async def _session(self) -> AsyncIterator[Payload]:
        connection = await self._connect(f"{await self._locate()}/?v=10&encoding=json")
        self._connection = connection
        if self._closed.is_set():
            await connection.close()
            return
        heartbeat: asyncio.Task[None] | None = None
        try:
            hello = await connection.receive()
            interval = float(hello["d"]["heartbeat_interval"]) / 1000
            await connection.send(self._identify())
            heartbeat = asyncio.create_task(self._heartbeat(connection, interval))
            while True:
                event = await connection.receive()
                if event.get("s") is not None:
                    self._sequence = event["s"]
                op = event.get("op")
                if op == DISPATCH and event.get("t") == "MESSAGE_CREATE":
                    yield event["d"]
                elif op == HEARTBEAT:
                    await connection.send(self._beat())
                elif op == HEARTBEAT_ACK:
                    self._acked = True
                elif op in (RECONNECT, INVALID_SESSION):
                    return
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError, GatewayClosedError):
                    await heartbeat
            self._connection = None

    async def _heartbeat(self, connection: GatewayConnection, interval: float) -> None:
        # Discord asks for a random jitter before the first beat so reconnects do not align.
        await self._clock.sleep(interval * random.random())
        while True:
            self._acked = False
            await connection.send(self._beat())
            await self._clock.sleep(interval)
            if not self._acked:
                # No ack within an interval: a zombie connection. Close it and reconnect.
                await connection.close()
                return

    def _beat(self) -> Payload:
        return {"op": HEARTBEAT, "d": self._sequence}

    def _identify(self) -> Payload:
        properties = {"os": sys.platform, "browser": "labhq", "device": "labhq"}
        return {
            "op": IDENTIFY,
            "d": {"token": self._token, "intents": INTENTS, "properties": properties},
        }
