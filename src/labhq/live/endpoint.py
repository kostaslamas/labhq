"""`/api/live`: a WebSocket that carries invalidations, never row data (ADR 0006).

Messages are `{"type": "invalidate", "topic": ..., "watermark": ...}` and, when nothing has
changed for `heartbeat_seconds`, `{"type": "heartbeat"}`. The client refetches through the
normal API, so authorization and response shapes stay in one place.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect, status

from labhq.api.deps import Owner, current_owner
from labhq.api.errors import ApiError
from labhq.api.hooks import LifespanHook, default_hooks
from labhq.live.broker import Broker, Subscription, default_broker
from labhq.live.settings import LiveSettings, get_live_settings

HEARTBEAT = {"type": "heartbeat"}


@dataclass(frozen=True)
class LiveState:
    broker: Broker
    settings: LiveSettings


def attach(broker: Broker, settings: LiveSettings | None = None) -> LifespanHook:
    """The startup hook that gives the app its broker; shutdown ends every open socket."""

    @asynccontextmanager
    async def hook(app: FastAPI) -> AsyncIterator[None]:
        app.state.live = LiveState(broker, settings or get_live_settings())
        try:
            yield
        finally:
            broker.close_all()

    return hook


async def authenticate(websocket: WebSocket) -> Owner | None:
    # The handshake is an HTTP request: the resolvers read its cookies and headers exactly as
    # they read a Request's. FastAPI's router-level dependency cannot, since it asks for a
    # `Request`, so this route is registered public and checks the owner itself.
    try:
        return await current_owner(cast(Request, websocket))
    except ApiError:
        return None


async def _send_changes(websocket: WebSocket, subscription: Subscription, heartbeat: float) -> None:
    try:
        await _send_loop(websocket, subscription, heartbeat)
    except WebSocketDisconnect:
        return


async def _send_loop(websocket: WebSocket, subscription: Subscription, heartbeat: float) -> None:
    while True:
        try:
            # A transport keepalive, not domain time: it runs on the event loop's clock.
            async with asyncio.timeout(heartbeat):
                changes = await subscription.get()
        except TimeoutError:
            await websocket.send_json(HEARTBEAT)
            continue
        if changes is None:
            return
        for change in changes:
            await websocket.send_json(
                {"type": "invalidate", "topic": change.topic, "watermark": change.watermark}
            )


async def _drain(websocket: WebSocket) -> None:
    # The client sends nothing; reading is how a closed socket is noticed while idle.
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return


live_router = APIRouter(tags=["live"])


@live_router.websocket("/live")
async def live_socket(websocket: WebSocket) -> None:
    if await authenticate(websocket) is None:
        # Closing before accept refuses the handshake (HTTP 403).
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    state: LiveState | None = getattr(websocket.app.state, "live", None)
    if state is None:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return
    # Subscribed before the handshake completes, so nothing published after it is missed.
    with state.broker.subscribe() as subscription:
        await websocket.accept()
        sender = asyncio.create_task(
            _send_changes(websocket, subscription, state.settings.heartbeat_seconds)
        )
        reader = asyncio.create_task(_drain(websocket))
        done, pending = await asyncio.wait({sender, reader}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    if sender in done:
        await websocket.close(code=status.WS_1001_GOING_AWAY)


default_hooks.register("live", attach(default_broker))
