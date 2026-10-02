"""Which actions need approval at which risk class, and who may resolve them (plan §5).

Both tables are data. A new action type or confirmation kind is one `register` call.
"""

from dataclasses import dataclass

from labhq.approvals.registry import Registry
from labhq.db.enums import RiskClass


@dataclass(frozen=True)
class ActionType:
    key: str
    risk_class: RiskClass


@dataclass(frozen=True)
class ConfirmationKind:
    """A way a human confirms a decision, and the risk classes it is strong enough for.

    Rule 7 of plan §5 lives here: a voice client registers with light only, so it can never
    approve a heavy action, whoever asks it to.
    """

    key: str
    approves: frozenset[RiskClass]

    def can_approve(self, risk_class: RiskClass) -> bool:
        return risk_class in self.approves


LIGHT = frozenset({RiskClass.LIGHT})
ANY_RISK = frozenset(RiskClass)

# Plan §5 table. Phase 1 executes only `push`; the rest are requested and decided now and
# gain executors as their phases land.
PHASE_1_ACTIONS: tuple[ActionType, ...] = (
    ActionType("start_meeting", RiskClass.LIGHT),
    ActionType("assign_task", RiskClass.LIGHT),
    ActionType("change_priority", RiskClass.LIGHT),
    ActionType("push", RiskClass.HEAVY),
    ActionType("merge", RiskClass.HEAVY),
    ActionType("delete_branch", RiskClass.HEAVY),
    ActionType("delete_project", RiskClass.HEAVY),
    ActionType("create_team", RiskClass.HEAVY),
    ActionType("exceed_budget", RiskClass.HEAVY),
    ActionType("host_intervention", RiskClass.HEAVY),
)

# The local operator at the CLI holds the machine already. Passkeys join in Phase 4 and a
# voice client in Phase 2 (light only), each as a new registration.
PHASE_1_CONFIRMATIONS: tuple[ConfirmationKind, ...] = (ConfirmationKind("cli", ANY_RISK),)

default_actions = Registry[ActionType]("action type")
for _action in PHASE_1_ACTIONS:
    default_actions.register(_action.key, _action)

default_confirmations = Registry[ConfirmationKind]("confirmation kind")
for _kind in PHASE_1_CONFIRMATIONS:
    default_confirmations.register(_kind.key, _kind)
