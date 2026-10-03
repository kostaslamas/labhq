"""The interface every agent adapter implements, and the values it exchanges with runs."""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentTool:
    """A tool the engine serves to an agent in its own process.

    `input_schema` is a JSON schema object; the handler receives the validated arguments and
    returns the text the agent reads. Each adapter decides how it exposes the tool.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[str]]
    read_only: bool = True


@dataclass(frozen=True)
class RunRequest:
    """What a run asks of an adapter. One request starts one adapter instance."""

    prompt: str
    cwd: Path | None = None
    # A session id from `agent_task_sessions`; the adapter continues that conversation.
    resume_session_id: str | None = None
    # `agents.config`, read by each adapter for the keys it understands.
    config: Mapping[str, Any] = field(default_factory=dict)
    # Adapter-specific hook matchers supplied by the caller (for example the push guard).
    hooks: Mapping[str, Any] | None = None
    # A run given its own tools gets only those: no shell, no file tools, nothing built in.
    # The Call Center agent (ADR 0004) is the first caller.
    tools: Sequence[AgentTool] = ()
    # The run this request belongs to; adapters that name external resources use it.
    run_id: int | None = None


@dataclass(frozen=True)
class AdapterEvent:
    """One element of the stream, stored as a `run_events` row. `payload` is JSON-safe."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterResult:
    """The terminal result of a run, as the adapter reports it.

    `cost_usd` stays the adapter's own number; `labhq.runs` converts it to micros through
    `labhq.money`, so no other code path handles a float amount (ADR 0002).
    """

    subtype: str
    is_error: bool
    session_id: str | None
    terminal_reason: str | None = None
    cost_usd: float | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    num_turns: int | None = None
    errors: list[str] = field(default_factory=list)
    # The run's final answer, when the adapter reports one.
    text: str | None = None


class AdapterError(RuntimeError):
    """The adapter could not produce a terminal result."""


class Adapter(Protocol):
    """A single agent run: start it, read its events, steer it, then read the result.

    `events()` ends after the adapter has a terminal result; `result()` is valid only then.
    An interrupt does not end the stream at once: the adapter still reports a result, with
    `terminal_reason` `aborted_streaming` (spikes/agent_sdk/RESULTS.md).
    """

    async def start(self, request: RunRequest) -> None: ...

    def events(self) -> AsyncIterator[AdapterEvent]: ...

    async def send(self, text: str) -> None: ...

    async def interrupt(self) -> None: ...

    def result(self) -> AdapterResult: ...

    async def close(self) -> None: ...
