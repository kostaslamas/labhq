"""One asyncio process: the MCP server and every registered loop, stopped together.

Shutdown order matters. The server stops accepting first, then the loops are cancelled
(a pass in flight is dropped; every duty is safe to repeat), and only then do live runs
get their interrupt, so no loop can start a run while they are being stopped.
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable, Iterator
from typing import Protocol

import uvicorn

from labhq.clock import Clock
from labhq.program.loops import LoopRegistry, run_loop
from labhq.program.services import Services
from labhq.program.settings import ProgramSettings

log = logging.getLogger(__name__)

STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class ProgramError(RuntimeError):
    """The program stopped for a reason the operator can act on."""


class Server(Protocol):
    should_exit: bool

    def serve(self) -> Awaitable[None]: ...


class ProgramServer(uvicorn.Server):
    """A uvicorn server that leaves signals to the program.

    uvicorn replaces the SIGINT and SIGTERM handlers and re-raises the signal once it has
    stopped, which would end the process with a signal status instead of exit code 0.
    """

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


class Program:
    def __init__(
        self,
        services: Services,
        loops: LoopRegistry[Services],
        server: Server,
        *,
        clock: Clock,
        settings: ProgramSettings,
    ) -> None:
        self._services = services
        self._loops = loops
        self._server = server
        self._clock = clock
        self._settings = settings
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self, *, handle_signals: bool = True) -> None:
        """Run until a stop signal or `request_stop()`; raise `ProgramError` if the server dies."""
        server_task = asyncio.create_task(self._serve(), name="server")
        loop_tasks = [
            asyncio.create_task(
                run_loop(
                    spec.name,
                    spec.interval(self._settings),
                    spec.build(self._services),
                    self._clock,
                ),
                name=f"loop-{spec.name}",
            )
            for spec in self._loops
        ]
        stopper = asyncio.create_task(self._stop.wait(), name="stop")
        with self._signals(enabled=handle_signals):
            try:
                await asyncio.wait({server_task, stopper}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                stopper.cancel()
                await self._shutdown(server_task, loop_tasks)
        if not self._stop.is_set():
            raise ProgramError("the server stopped unexpectedly")

    async def _serve(self) -> None:
        try:
            await self._server.serve()
        except SystemExit as error:
            # uvicorn exits the interpreter when it cannot bind; surface that as an error.
            raise ProgramError("the server could not start (is the port in use?)") from error

    async def _shutdown(
        self, server_task: "asyncio.Task[None]", loop_tasks: list["asyncio.Task[None]"]
    ) -> None:
        self._server.should_exit = True
        grace = self._settings.shutdown_grace_seconds
        try:
            async with asyncio.timeout(grace):
                await asyncio.wait({server_task})
        except TimeoutError:
            log.warning("the server did not stop within %ss; cancelling it", grace)
            server_task.cancel()
        for task in loop_tasks:
            task.cancel()
        await asyncio.gather(*loop_tasks, return_exceptions=True)
        await asyncio.gather(server_task, return_exceptions=True)
        await self._services.close()

    @contextlib.contextmanager
    def _signals(self, *, enabled: bool) -> Iterator[None]:
        if not enabled:
            yield
            return
        loop = asyncio.get_running_loop()
        try:
            for number in STOP_SIGNALS:
                loop.add_signal_handler(number, self.request_stop)
        except NotImplementedError:
            # Windows' proactor loop has no signal handlers; a plain one (Ctrl+C) hands the
            # stop to the loop instead.
            with _plain_signal_handlers(loop, self.request_stop):
                yield
            return
        try:
            yield
        finally:
            for number in STOP_SIGNALS:
                loop.remove_signal_handler(number)


@contextlib.contextmanager
def _plain_signal_handlers(
    loop: asyncio.AbstractEventLoop, stop: Callable[[], None]
) -> Iterator[None]:
    previous = {
        number: signal.signal(number, lambda *_: loop.call_soon_threadsafe(stop))
        for number in STOP_SIGNALS
    }
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
