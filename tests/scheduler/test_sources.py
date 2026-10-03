"""Sources are a registry; a new source is a registration, and each briefs the agent."""

from datetime import UTC, datetime

import pytest

from labhq.db.enums import WakeupSource
from labhq.db.models import Task, WakeupRequest
from labhq.scheduler import SourceRegistry, TemplateHandler, UnknownSourceError

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def _request(**values: object) -> WakeupRequest:
    return WakeupRequest(
        agent_id=1,
        source=WakeupSource.COMMENT,
        idempotency_key="k",
        reason=values.get("reason", ""),
        coalesced_count=values.get("coalesced_count", 0),
        created_at=NOW,
        updated_at=NOW,
    )


def test_the_prompt_carries_reason_merges_and_task() -> None:
    handler = TemplateHandler(requires_task=True, opening="You were mentioned.")
    task = Task(id=7, project_id=1, title="Fix login", description="Users cannot log in.")
    prompt = handler.prompt(_request(reason="see #3", coalesced_count=2), task)
    assert prompt.splitlines() == [
        "You were mentioned.",
        "Reason: see #3",
        "2 further wakeups arrived meanwhile.",
        "Task #7: Fix login",
        "Users cannot log in.",
    ]


def test_a_bare_wakeup_is_just_the_opening() -> None:
    assert TemplateHandler(False, "Check in.").prompt(_request(), None) == "Check in."


def test_an_unregistered_source_is_an_error_and_duplicates_are_refused() -> None:
    registry = SourceRegistry()
    with pytest.raises(UnknownSourceError):
        registry.handler(WakeupSource.MEETING)
    registry.register(WakeupSource.MEETING, TemplateHandler(False, "Meet."))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(WakeupSource.MEETING, TemplateHandler(False, "Again."))
    registry.register(WakeupSource.MEETING, TemplateHandler(False, "Again."), replace=True)
    assert registry.sources() == [WakeupSource.MEETING]
