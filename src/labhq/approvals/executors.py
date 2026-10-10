"""`action_type -> executor`: what the engine does once an action is approved.

Agents only request. An executor runs in the engine, never in a worker, and returns a JSON
record of what it did, which the approval stores as its execution.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from labhq.approvals.merge import MERGE_ACTION, MergePayload, merge_branch
from labhq.approvals.push import PUSH_ACTION, PushPayload, push_branch
from labhq.approvals.registry import Registry
from labhq.health.intervention import INTERVENTION_ACTION, HostIntervention, InterventionPayload
from labhq.modelpolicy.apply import CHANGE_ACTION, apply_change, validate_change

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
default_executors.register(
    INTERVENTION_ACTION,
    Executor(run=HostIntervention().run, validate=InterventionPayload.model_validate),
)
default_executors.register(
    MERGE_ACTION, Executor(run=merge_branch, validate=MergePayload.model_validate)
)
default_executors.register(CHANGE_ACTION, Executor(run=apply_change, validate=validate_change))
