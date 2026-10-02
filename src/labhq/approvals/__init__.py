"""Approvals: agents request, a human decides, the engine executes (plan §5).

Risk classes, executors and confirmation kinds are registries. A new action type is a
registration in `default_actions` (and `default_executors` when the engine can run it).
"""

from labhq.approvals.executors import Executor, Payload, default_executors
from labhq.approvals.policy import (
    ActionType,
    ConfirmationKind,
    default_actions,
    default_confirmations,
)
from labhq.approvals.push import PUSH_ACTION, PushPayload, push_branch, push_payload
from labhq.approvals.registry import Registry, UnknownEntryError
from labhq.approvals.service import (
    ApprovalError,
    ApprovalNotFoundError,
    ApprovalNotPendingError,
    ApprovalService,
    ConfirmationNotAllowedError,
)

__all__ = [
    "PUSH_ACTION",
    "ActionType",
    "ApprovalError",
    "ApprovalNotFoundError",
    "ApprovalNotPendingError",
    "ApprovalService",
    "ConfirmationKind",
    "ConfirmationNotAllowedError",
    "Executor",
    "Payload",
    "PushPayload",
    "Registry",
    "UnknownEntryError",
    "default_actions",
    "default_confirmations",
    "default_executors",
    "push_branch",
    "push_payload",
]
