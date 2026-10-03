"""External approval gates (ADR 0007): heavy approvals decided with a passkey elsewhere."""

from labhq.approvals.gates import http as _http  # noqa: F401  (registers the `http` gate)
from labhq.approvals.gates.base import (
    GateAdapter,
    GateAnswer,
    GateError,
    GateRequest,
    GateStatus,
    build_gate,
    gate_adapters,
)
from labhq.approvals.gates.relay import GateRelay, summarize
from labhq.approvals.gates.settings import GateSettings

__all__ = [
    "GateAdapter",
    "GateAnswer",
    "GateError",
    "GateRelay",
    "GateRequest",
    "GateSettings",
    "GateStatus",
    "build_gate",
    "gate_adapters",
    "summarize",
]
