"""The MCP app on a background thread, so the tunnel has something to reach during the checks."""

import threading
import time

import uvicorn
from starlette.types import ASGIApp

from labhq.onboard.base import StepError


class ThreadServer:
    def __init__(self, app: ASGIApp, *, host: str, port: int) -> None:
        # No access log: the secret path would land in it.
        config = uvicorn.Config(app, host=host, port=port, access_log=False, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._where = f"{host}:{port}"

    def start(self, timeout: float) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                self.stop()
                raise StepError(
                    f"the server could not start on {self._where} (is the port in use? "
                    "pick another with --port)"
                )
            self._thread.join(0.05)

    def stop(self) -> None:
        """Safe to repeat. The tunnel may outlive it: `labhq serve` takes over the port."""
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join()
