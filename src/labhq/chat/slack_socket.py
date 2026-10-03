"""A minimal Slack Socket Mode client: open a link, acknowledge envelopes, reconnect.

Socket Mode delivers Events API payloads over a WebSocket the app opens itself, so labhq
needs no public URL. Each envelope is acknowledged at once, before it is yielded; Slack
redelivers unacknowledged ones, and the adapter drops the duplicates.
"""

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from labhq.chat.base import ChatError
from labhq.clock import Clock

EVENTS_API = "events_api"
DISCONNECT = "disconnect"
# Slack disabled Socket Mode for the app: reconnecting cannot succeed.
LINK_DISABLED = "link_disabled"

# The link URL carries a ticket that authenticates the socket, and websockets logs it at
# DEBUG. A dedicated logger with its own level keeps those lines out under a global DEBUG.
_SOCKET_LOGGER = logging.getLogger("labhq.chat.slack.websocket")
_SOCKET_LOGGER.setLevel(logging.INFO)

type Envelope = dict[str, Any]


class SocketClosedError(Exception):
    pass


class SocketConnection(Protocol):
    async def send(self, payload: Envelope) -> None: ...

    async def receive(self) -> Envelope:
        """The next envelope; raises `SocketClosedError` once the connection is gone."""
        ...

    async def close(self) -> None: ...


type SocketConnector = Callable[[str], Awaitable[SocketConnection]]


class _WebSocketConnection:
    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket

    async def send(self, payload: Envelope) -> None:
        try:
            await self._socket.send(json.dumps(payload))
        except ConnectionClosed:
            raise SocketClosedError from None

    async def receive(self) -> Envelope:
        try:
            raw = await self._socket.recv()
        except ConnectionClosed:
            raise SocketClosedError from None
        envelope: Envelope = json.loads(raw)
        return envelope

    async def close(self) -> None:
        await self._socket.close()


async def websocket_connect(url: str) -> SocketConnection:
    try:
        return _WebSocketConnection(await connect(url, logger=_SOCKET_LOGGER))
    except (OSError, WebSocketException) as error:
        # The error text can quote the URL, ticket included.
        raise SocketClosedError(type(error).__name__) from None


class SocketMode:
    def __init__(
        self,
        *,
        locate: Callable[[], Awaitable[str]],
        connect: SocketConnector,
        clock: Clock,
        reconnect_seconds: float,
    ) -> None:
        self._locate = locate
        self._connect = connect
        self._clock = clock
        self._reconnect_seconds = reconnect_seconds
        self._connection: SocketConnection | None = None
        self._closed = False

    async def events(self) -> AsyncIterator[Envelope]:
        """The `event` of every Events API envelope, across reconnects, until `close`."""
        while not self._closed:
            try:
                async for event in self._session():
                    yield event
            except SocketClosedError:
                pass
            if not self._closed:
                await self._clock.sleep(self._reconnect_seconds)

    async def close(self) -> None:
        self._closed = True
        if self._connection is not None:
            await self._connection.close()

    async def _session(self) -> AsyncIterator[Envelope]:
        connection = await self._connect(await self._locate())
        self._connection = connection
        try:
            while not self._closed:
                envelope = await connection.receive()
                if "envelope_id" in envelope:
                    await connection.send({"envelope_id": envelope["envelope_id"]})
                kind = envelope.get("type")
                if kind == EVENTS_API:
                    yield envelope.get("payload", {}).get("event", {})
                elif kind == DISCONNECT:
                    if envelope.get("reason") == LINK_DISABLED:
                        raise ChatError("slack disabled socket mode for this app")
                    return
        finally:
            self._connection = None
            await connection.close()
