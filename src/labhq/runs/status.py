"""Terminal adapter results mapped to run statuses. The mapping is data, not branches."""

from labhq.adapters.base import AdapterResult
from labhq.db.enums import RunStatus

# Consulted first: an interrupt is reported as an error subtype, yet it is not a failure
# (spikes/agent_sdk/RESULTS.md, interrupt).
STATUS_BY_TERMINAL_REASON: dict[str, RunStatus] = {
    "aborted_streaming": RunStatus.INTERRUPTED,
    "aborted_tools": RunStatus.INTERRUPTED,
}

# Then (subtype, is_error). A "success" subtype with `is_error` is a failed API call.
STATUS_BY_SUBTYPE: dict[tuple[str, bool], RunStatus] = {
    ("success", False): RunStatus.SUCCEEDED,
}

# Everything else, e.g. error_max_turns or error_during_execution without an abort.
DEFAULT_STATUS = RunStatus.FAILED


def status_for(result: AdapterResult) -> RunStatus:
    by_reason = STATUS_BY_TERMINAL_REASON.get(result.terminal_reason or "")
    if by_reason is not None:
        return by_reason
    return STATUS_BY_SUBTYPE.get((result.subtype, result.is_error), DEFAULT_STATUS)
