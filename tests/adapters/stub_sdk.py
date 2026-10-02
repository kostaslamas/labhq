"""A scripted stand-in for `ClaudeSDKClient`, at the boundary the Claude adapter uses.

It yields real SDK message objects, so the adapter's translation runs unchanged. The
interrupt result mirrors what the spike measured against a real login.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
)

from labhq.adapters import ClaudeAdapter

MODEL = "claude-haiku-4-5-20251001"
CLI_PATH = Path("/opt/claude/bin/claude")


def result_message(session_id: str, **overrides: Any) -> ResultMessage:
    fields: dict[str, Any] = {
        "subtype": "success",
        "duration_ms": 1200,
        "duration_api_ms": 900,
        "is_error": False,
        "num_turns": 1,
        "session_id": session_id,
        "total_cost_usd": 0.0097,
        "usage": {"input_tokens": 410, "output_tokens": 12, "cache_read_input_tokens": 3000},
        "terminal_reason": "completed",
        "model_usage": {MODEL: {"inputTokens": 410, "outputTokens": 12}},
    }
    fields.update(overrides)
    return ResultMessage(**fields)


def _default_messages() -> list[object]:
    return [
        SystemMessage(subtype="init", data={"model": MODEL}),
        AssistantMessage(content=[TextBlock(text="OK")], model=MODEL),
    ]


@dataclass
class StubScript:
    messages: list[object] = field(default_factory=_default_messages)
    session_id: str = "stub-session-1"
    wait_for_interrupt: bool = False
    # None ends the stream without a result, which a real CLI does only when it dies.
    result_overrides: dict[str, Any] | None = field(default_factory=dict)
    options: list[ClaudeAgentOptions] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    interrupts: int = 0
    disconnects: int = 0


class StubClient:
    def __init__(self, options: ClaudeAgentOptions, script: StubScript) -> None:
        self._options = options
        self._script = script
        self._interrupted = asyncio.Event()
        script.options.append(options)

    async def connect(self) -> None:
        return None

    async def query(self, prompt: str) -> None:
        self._script.queries.append(prompt)

    async def receive_response(self) -> AsyncIterator[object]:
        script = self._script
        for message in script.messages:
            yield message
        if script.wait_for_interrupt:
            await self._interrupted.wait()
        if script.result_overrides is None:
            return
        session_id = self._options.resume or script.session_id
        overrides = dict(script.result_overrides)
        if self._interrupted.is_set():
            overrides |= {
                "subtype": "error_during_execution",
                "is_error": True,
                "terminal_reason": "aborted_streaming",
            }
        yield result_message(session_id, **overrides)

    async def interrupt(self) -> None:
        self._script.interrupts += 1
        self._interrupted.set()

    async def disconnect(self) -> None:
        self._script.disconnects += 1


def stub_claude(
    script: StubScript, environ: dict[str, str] | None = None
) -> Callable[[], ClaudeAdapter]:
    """An adapter factory whose adapters talk to `script` instead of a CLI."""

    def make() -> ClaudeAdapter:
        return ClaudeAdapter(
            cli_path=CLI_PATH,
            client_factory=lambda options: StubClient(options, script),
            environ=environ if environ is not None else {"PATH": "/usr/bin"},
        )

    return make
