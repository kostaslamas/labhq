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

# Outward-facing actions of departments (issue #171): they reach people or services outside
# labhq, so each is heavy and needs the owner's passkey. No executor is registered yet: they
# can be requested and approved, and executors arrive later as registrations.
OUTWARD_ACTIONS: tuple[ActionType, ...] = (
    ActionType("send_email", RiskClass.HEAVY),
    ActionType("send_message", RiskClass.HEAVY),
    ActionType("publish", RiskClass.HEAVY),
    ActionType("make_payment", RiskClass.HEAVY),
    ActionType("sign_up_service", RiskClass.HEAVY),
)

# The local operator at the CLI holds the machine already. The Call Center voice line is
# light only (plan §5, rule 7), and so is a tap in the web UI. A passkey is the strong
# confirmation that may approve heavy: the API accepts it only after a step-up assertion
# (`labhq.auth.verify_step_up`).
PHASE_1_CONFIRMATIONS: tuple[ConfirmationKind, ...] = (
    ConfirmationKind("cli", ANY_RISK),
    ConfirmationKind("voice", LIGHT),
    ConfirmationKind("tap", LIGHT),
    ConfirmationKind("passkey", ANY_RISK),
    # The CEO decides light actions itself (owner decision, issue #168). Light only, so the
    # CEO can request a merge or a push but never approve one.
    ConfirmationKind("ceo", LIGHT),
    # An external approval gate proved a passkey; the gate adapter refuses weaker proofs
    # before it ever asks for this kind (approvals.gates).
    ConfirmationKind("external_gate", ANY_RISK),
)

default_actions = Registry[ActionType]("action type")
for _action in (*PHASE_1_ACTIONS, *OUTWARD_ACTIONS):
    default_actions.register(_action.key, _action)

default_confirmations = Registry[ConfirmationKind]("confirmation kind")
for _kind in PHASE_1_CONFIRMATIONS:
    default_confirmations.register(_kind.key, _kind)
