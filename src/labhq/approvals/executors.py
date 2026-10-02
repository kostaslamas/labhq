"""`action_type -> executor`: what the engine does once an action is approved.

Agents only request. An executor runs in the engine, never in a worker, and returns a JSON
record of what it did, which the approval stores as its execution.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from labhq.approvals.push import PUSH_ACTION, PushPayload, push_branch
from labhq.approvals.registry import Registry

Payload = Mapping[str, Any]


@dataclass(frozen=True)
class Executor:
    run: Callable[[Payload], dict[str, Any]]
    # Checked when the action is requested, so a malformed request never waits for a human.
    validate: Callable[[Payload], object] | None = None


default_executors = Registry[Executor]("executor")
default_executors.register(
    PUSH_ACTION, Executor(run=push_branch, validate=PushPayload.model_validate)
)
