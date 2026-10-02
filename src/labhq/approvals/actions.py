"""What each action type risks and how the engine carries it out once approved.

Both are registries keyed by the action type stored in `approvals.type`. Classifying or
executing a new action type is a registration here, never an edit to the service.
"""

from collections.abc import Callable, Mapping
from typing import Any

from labhq.approvals.push import PUSH, execute_push
from labhq.approvals.registry import Registry
from labhq.db.enums import RiskClass

# Receives the approved payload, returns the record stored in `approvals.execution`, and
# raises on failure. Executors run in the engine process, never in a worker environment.
Executor = Callable[[Mapping[str, Any]], dict[str, Any]]

RiskRegistry = Registry[RiskClass]
ExecutorRegistry = Registry[Executor]

# Plan §5: publishing, merging, deleting and forming teams are heavy decisions.
PHASE_1_RISK_CLASSES: Mapping[str, RiskClass] = {
    PUSH: RiskClass.HEAVY,
    "merge": RiskClass.HEAVY,
    "delete_branch": RiskClass.HEAVY,
    "create_team": RiskClass.HEAVY,
}


def risk_registry(entries: Mapping[str, RiskClass] = PHASE_1_RISK_CLASSES) -> RiskRegistry:
    registry = RiskRegistry("action type")
    for action_type, risk_class in entries.items():
        registry.register(action_type, risk_class)
    return registry


default_risks = risk_registry()
default_executors = ExecutorRegistry("executor")
default_executors.register(PUSH, execute_push)
