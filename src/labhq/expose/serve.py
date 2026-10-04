"""Serve the app and expose it: the tunnel opens only once the server answers locally."""

import asyncio
import threading
from collections.abc import Callable
from typing import Protocol

import uvicorn
from starlette.types import ASGIApp

from labhq.clock import Clock
from labhq.expose.base import Exposure, ExposureAdapter, ExposureError
from labhq.expose.verify import connector_url, verify_connector

type Verifier = Callable[[str, str], None]


def open_verified(
    adapter: ExposureAdapter, port: int, secret: str, *, verify: Verifier = verify_connector
) -> tuple[Exposure, str]:
    """Open the exposure and prove it with one `initialize`; returns it with the connector URL.

    A failed proof stops the exposure before the error propagates, so nothing stays public.
    """
    exposure = adapter.open(port)
    try:
        verify(exposure.url, secret)
    except BaseException:
        exposure.close()
        raise
    return exposure, connector_url(exposure.url, secret)


def serve_exposed(
    app: ASGIApp,
    *,
    host: str,
    port: int,
    secret: str,
    adapter: ExposureAdapter,
    announce: Callable[[str], None],
    verify: Verifier = verify_connector,
) -> None:
    """Run the server until it stops, exposing it; `announce` receives the connector URL once."""
    # No access log: the secret path would land in it.
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    exposure: Exposure | None = None
    try:
        while not server.started:
            if not thread.is_alive():
                raise ExposureError(f"the server could not start on {host}:{port}")
            thread.join(0.05)
        exposure, url = open_verified(adapter, port, secret, verify=verify)
        announce(url)
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        if exposure is not None:
            exposure.close()
        server.should_exit = True
        thread.join()


class StartedServer(Protocol):
    @property
    def started(self) -> bool: ...


async def expose_running(
    server: StartedServer,
    *,
    port: int,
    secret: str,
    adapter: ExposureAdapter,
    announce: Callable[[str], None],
    clock: Clock,
    verify: Verifier = verify_connector,
) -> None:
    """Expose a server another task runs, once it answers; hold the exposure until cancelled.

    `serve_exposed` owns a server of its own; `labhq serve` already runs one inside the
    program, so this opens the tunnel next to it. A failure raises `ExposureError`, and the
    caller must stop the program: a server that was meant to be public never stays private.
    """
    while not server.started:
        await clock.sleep(0.05)
    opened: list[Exposure] = []

    def open_it() -> str:
        exposure, url = open_verified(adapter, port, secret, verify=verify)
        opened.append(exposure)
        return url

    try:
        # The tunnel binary and the proof block, so they run off the event loop.
        url = await asyncio.to_thread(open_it)
        announce(url)
        await asyncio.Event().wait()
    finally:
        for exposure in opened:
            exposure.close()
