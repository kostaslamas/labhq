"""Pure budget arithmetic: integer micro-USD in, a decision out (ADR 0002)."""

from enum import StrEnum

from labhq.budgets.settings import BudgetSettings


class Decision(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    STOP = "stop"


# Least to most strict; the stricter of two decisions is the one later in this tuple.
_SEVERITY = (Decision.ALLOW, Decision.WARN, Decision.STOP)


def require_micros(name: str, value: object) -> int:
    """Reject anything but an int, so a float can never reach a comparison."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be integer micro-USD, got {type(value).__name__}")
    return value


def stricter(*decisions: Decision) -> Decision:
    return max(decisions, key=_SEVERITY.index, default=Decision.ALLOW)


def decide(spent_micros: int, budget_micros: int | None, settings: BudgetSettings) -> Decision:
    """Compare spend with a budget; `None` means no limit at this level."""
    spent = require_micros("spent_micros", spent_micros)
    if budget_micros is None:
        return Decision.ALLOW
    budget = require_micros("budget_micros", budget_micros)
    # Strictest threshold first; the first one reached decides.
    thresholds = ((settings.stop_percent, Decision.STOP), (settings.warn_percent, Decision.WARN))
    for percent, decision in thresholds:
        if spent * 100 >= budget * percent:
            return decision
    return Decision.ALLOW
