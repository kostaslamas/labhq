"""A deterministic, scripted adapter. Every engine test runs on it instead of a model."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from labhq.adapters.base import AdapterError, AdapterEvent, AdapterResult, RunRequest

INTERRUPTED_SUBTYPE = "error_during_execution"
INTERRUPTED_REASON = "aborted_streaming"


def _default_events() -> list[AdapterEvent]:
    return [
        AdapterEvent("system", {"subtype": "init"}),
        AdapterEvent("assistant", {"text": "OK"}),
    ]


def _default_usage() -> dict[str, Any]:
    return {"input_tokens": 120, "output_tokens": 30}


@dataclass
class FakeScript:
    """What the fake does, and what it saw. One script may serve several runs.

    The defaults describe a short successful run. `wait_for_interrupt` holds the stream
    after the scripted events until `interrupt()` arrives, then reports what the SDK
    reports for an interrupt. `fail_with` raises after the scripted events.
    """

    events: list[AdapterEvent] = field(default_factory=_default_events)
    subtype: str = "success"
    is_error: bool = False
    terminal_reason: str | None = "completed"
    cost_usd: float | None = 0.0125
    usage: dict[str, Any] = field(default_factory=_default_usage)
    session_id: str = "fake-session-1"
    model: str | None = "fake-model"
    text: str | None = "OK"
    wait_for_interrupt: bool = False
    fail_with: Exception | None = None
    # Observations, appended by every adapter built on this script.
    requests: list[RunRequest] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    interrupts: int = 0
    closes: int = 0


class FakeAdapter:
    def __init__(self, script: FakeScript | None = None) -> None:
        self.script = script if script is not None else FakeScript()
        self._request: RunRequest | None = None
        self._interrupted = asyncio.Event()
        self._result: AdapterResult | None = None

    async def start(self, request: RunRequest) -> None:
        self._request = request
        self.script.requests.append(request)

    async def events(self) -> AsyncIterator[AdapterEvent]:
        if self._request is None:
            raise AdapterError("start() was not called")
        for event in self.script.events:
            yield event
        if self.script.fail_with is not None:
            raise self.script.fail_with
        if self.script.wait_for_interrupt:
            await self._interrupted.wait()
        self._result = self._final_result()
        yield AdapterEvent("result", {"subtype": self._result.subtype})

    async def send(self, text: str) -> None:
        self.script.inputs.append(text)

    async def interrupt(self) -> None:
        self.script.interrupts += 1
        self._interrupted.set()

    def result(self) -> AdapterResult:
        if self._result is None:
            raise AdapterError("the run has no result yet")
        return self._result

    async def close(self) -> None:
        self.script.closes += 1

    def _final_result(self) -> AdapterResult:
        assert self._request is not None
        script = self.script
        # A resumed SDK session keeps its id (spikes/agent_sdk/RESULTS.md, resume).
        session_id = self._request.resume_session_id or script.session_id
        interrupted = self._interrupted.is_set()
        return AdapterResult(
            subtype=INTERRUPTED_SUBTYPE if interrupted else script.subtype,
            is_error=True if interrupted else script.is_error,
            terminal_reason=INTERRUPTED_REASON if interrupted else script.terminal_reason,
            session_id=session_id,
            cost_usd=script.cost_usd,
            usage=dict(script.usage),
            model=script.model,
            num_turns=1,
            text=None if interrupted else script.text,
        )
