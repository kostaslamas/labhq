"""How a decision was confirmed, and which risk classes each kind may resolve.

Phase 1 knows only `cli`, the local operator at a terminal. Passkeys (Phase 4) arrive as a
new registration. A voice client registers in Phase 2 resolving `light` only: plan §5,
rule 7 says it can never resolve a heavy approval, and this table is where that holds.
"""

from dataclasses import dataclass

from labhq.approvals.registry import Registry
from labhq.db.enums import RiskClass


@dataclass(frozen=True)
class ConfirmationKind:
    key: str
    resolves: frozenset[RiskClass]

    def can_resolve(self, risk_class: RiskClass) -> bool:
        return risk_class in self.resolves


ConfirmationRegistry = Registry[ConfirmationKind]

CLI = ConfirmationKind("cli", frozenset(RiskClass))


def confirmation_registry(*kinds: ConfirmationKind) -> ConfirmationRegistry:
    registry = ConfirmationRegistry("confirmation kind")
    for kind in kinds:
        registry.register(kind.key, kind)
    return registry


default_confirmations = confirmation_registry(CLI)
