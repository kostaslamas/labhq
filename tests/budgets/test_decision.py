"""Pure budget arithmetic: thresholds from settings, integer micros only."""

import pytest
from pydantic import ValidationError

from labhq.budgets import BudgetSettings, Decision, decide, stricter

DEFAULTS = BudgetSettings()


@pytest.mark.parametrize(
    ("spent", "expected"),
    [
        (0, Decision.ALLOW),
        (799_999, Decision.ALLOW),
        (800_000, Decision.WARN),
        (999_999, Decision.WARN),
        (1_000_000, Decision.STOP),
        (5_000_000, Decision.STOP),
    ],
)
def test_default_thresholds_are_80_and_100_percent(spent: int, expected: Decision) -> None:
    assert decide(spent, 1_000_000, DEFAULTS) is expected


def test_missing_budget_means_no_limit() -> None:
    assert decide(10**15, None, DEFAULTS) is Decision.ALLOW


def test_thresholds_come_from_settings() -> None:
    settings = BudgetSettings(warn_percent=50, stop_percent=75)
    assert decide(499, 1_000, settings) is Decision.ALLOW
    assert decide(500, 1_000, settings) is Decision.WARN
    assert decide(750, 1_000, settings) is Decision.STOP


def test_thresholds_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_BUDGET_WARN_PERCENT", "90")
    settings = BudgetSettings()
    assert (settings.warn_percent, settings.stop_percent) == (90, 100)
    assert decide(899, 1_000, settings) is Decision.ALLOW


@pytest.mark.parametrize(
    "overrides",
    [{"warn_percent": 80.5}, {"warn_percent": 0}, {"warn_percent": 101, "stop_percent": 100}],
)
def test_invalid_thresholds_are_rejected(overrides: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        BudgetSettings(**overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("spent", "budget"), [(0.5, 1_000_000), (500_000, 1e6), (True, 10), (10, "100")]
)
def test_a_non_integer_amount_never_reaches_the_comparison(spent: object, budget: object) -> None:
    with pytest.raises(TypeError, match="integer micro-USD"):
        decide(spent, budget, DEFAULTS)  # type: ignore[arg-type]


def test_comparison_is_exact_where_float_division_is_not() -> None:
    # Exactly 80% of a budget large enough (still within a 64-bit column) that float
    # division rounds the ratio below 0.8; integer arithmetic does not.
    budget = 1_152_921_504_606_847_105
    spent = 922_337_203_685_477_684
    assert spent * 100 == budget * 80
    assert float(spent) / float(budget) < 0.8
    assert decide(spent, budget, DEFAULTS) is Decision.WARN
    assert decide(spent - 1, budget, DEFAULTS) is Decision.ALLOW


@pytest.mark.parametrize(
    ("decisions", "expected"),
    [
        ((Decision.ALLOW, Decision.WARN), Decision.WARN),
        ((Decision.STOP, Decision.WARN), Decision.STOP),
        ((Decision.ALLOW, Decision.STOP), Decision.STOP),
        ((Decision.ALLOW,), Decision.ALLOW),
    ],
)
def test_the_stricter_decision_wins(decisions: tuple[Decision, ...], expected: Decision) -> None:
    assert stricter(*decisions) is expected
