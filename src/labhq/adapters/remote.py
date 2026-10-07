"""The `remote` adapter: a manager whose team lives on another labhq (issue #188).

A run does not think. It queues the task as an order for the node the manager represents; the
node's own poll takes it from there. The run ends once the order is queued, with no cost, and
the node's reports arrive later as ordinary task reports. An interrupt before the order is
queued cancels it: nothing leaves this machine.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from labhq.adapters.base import AdapterError, AdapterEvent, AdapterResult, RunRequest

INTERRUPTED_SUBTYPE = "error_during_execution"
INTERRUPTED_REASON = "aborted_streaming"


class OrderQueue(Protocol):
    async def queue(self, run_id: int) -> str:
        """Queue the order the run stands for; the answer says what was queued."""
        ...


class RemoteAdapter:
    def __init__(self, orders: OrderQueue) -> None:
        self._orders = orders
        self._request: RunRequest | None = None
        self._interrupted = asyncio.Event()
        self._result: AdapterResult | None = None

    async def start(self, request: RunRequest) -> None:
        if request.run_id is None:
            raise AdapterError("a remote run needs a run id to queue its order under")
        self._request = request

    async def events(self) -> AsyncIterator[AdapterEvent]:
        request = self._request
        if request is None or request.run_id is None:
            raise AdapterError("start() was not called")
        yield AdapterEvent("system", {"subtype": "init"})
        yield AdapterEvent("assistant", {"text": "Sending the order to the remote node."})
        if self._interrupted.is_set():
            self._result = self._finish(request, interrupted=True)
        else:
            try:
                queued = await self._orders.queue(request.run_id)
            except Exception as error:
                raise AdapterError(f"could not queue the order: {error}") from error
            yield AdapterEvent("assistant", {"text": queued})
            self._result = self._finish(request, text=queued)
        yield AdapterEvent("result", {"subtype": self._result.subtype})

    async def send(self, text: str) -> None:
        # The order is whole once queued; there is no conversation to steer.
        raise AdapterError("a remote manager takes no further input")

    async def interrupt(self) -> None:
        self._interrupted.set()

    def result(self) -> AdapterResult:
        if self._result is None:
            raise AdapterError("the run has no result yet")
        return self._result

    async def close(self) -> None:
        return None

    @staticmethod
    def _finish(
        request: RunRequest, *, interrupted: bool = False, text: str | None = None
    ) -> AdapterResult:
        return AdapterResult(
            subtype=INTERRUPTED_SUBTYPE if interrupted else "success",
            is_error=interrupted,
            terminal_reason=INTERRUPTED_REASON if interrupted else "completed",
            # A resumed run keeps its session id, like every adapter (contract `resume`).
            session_id=request.resume_session_id or f"remote-{request.run_id}",
            cost_usd=None,
            num_turns=1,
            text=text,
        )
