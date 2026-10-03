"""Translation of Agent SDK messages into `run_events` rows and a terminal result."""

import dataclasses
import json
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    UserMessage,
)
from claude_agent_sdk.types import RateLimitEvent, StreamEvent

from labhq.adapters.base import AdapterEvent, AdapterResult

# A message type the table does not know is still stored, under its class name.
EVENT_KINDS: dict[type, str] = {
    AssistantMessage: "assistant",
    UserMessage: "user",
    SystemMessage: "system",
    ResultMessage: "result",
    StreamEvent: "stream_event",
    RateLimitEvent: "rate_limit",
}


def json_safe(value: Any) -> Any:
    # Payloads go into a JSON column; anything the encoder does not know becomes text.
    return json.loads(json.dumps(value, default=str))


def to_event(message: object) -> AdapterEvent:
    kind = EVENT_KINDS.get(type(message), type(message).__name__)
    if dataclasses.is_dataclass(message) and not isinstance(message, type):
        payload = dataclasses.asdict(message)
    else:
        payload = {"repr": repr(message)}
    return AdapterEvent(kind, json_safe(payload))


def to_result(message: ResultMessage, model: str | None) -> AdapterResult:
    # `model_usage` names every model the turn used; the last assistant message is the
    # fallback for older CLIs that omit it.
    models = list(message.model_usage or {})
    return AdapterResult(
        subtype=message.subtype,
        is_error=message.is_error,
        session_id=message.session_id or None,
        terminal_reason=message.terminal_reason,
        cost_usd=message.total_cost_usd,
        usage=json_safe(message.usage or {}),
        model=models[0] if models else model,
        num_turns=message.num_turns,
        errors=list(message.errors or []),
        text=message.result,
    )
