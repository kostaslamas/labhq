"""Terminal results map to run statuses through tables, checked case by case."""

import pytest

from labhq.adapters import AdapterResult
from labhq.db.enums import RunStatus
from labhq.runs import status_for
from labhq.runs.status import STATUS_BY_TERMINAL_REASON


@pytest.mark.parametrize(
    ("subtype", "is_error", "terminal_reason", "expected"),
    [
        ("success", False, "completed", RunStatus.SUCCEEDED),
        ("success", False, None, RunStatus.SUCCEEDED),
        # The CLI reports a failed API call (429, 529) as an error "success".
        ("success", True, "completed", RunStatus.FAILED),
        ("error_during_execution", True, "aborted_streaming", RunStatus.INTERRUPTED),
        ("error_during_execution", True, "aborted_tools", RunStatus.INTERRUPTED),
        ("error_during_execution", True, None, RunStatus.FAILED),
        ("error_max_turns", True, "max_turns", RunStatus.FAILED),
        ("error_max_budget_usd", True, None, RunStatus.FAILED),
        ("something_new", False, None, RunStatus.FAILED),
    ],
)
def test_status_for(
    subtype: str, is_error: bool, terminal_reason: str | None, expected: RunStatus
) -> None:
    result = AdapterResult(
        subtype=subtype, is_error=is_error, session_id="s", terminal_reason=terminal_reason
    )
    assert status_for(result) is expected


def test_a_new_terminal_reason_is_a_table_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(STATUS_BY_TERMINAL_REASON, "timeout", RunStatus.TIMED_OUT)
    result = AdapterResult(
        subtype="error", is_error=True, session_id=None, terminal_reason="timeout"
    )
    assert status_for(result) is RunStatus.TIMED_OUT
