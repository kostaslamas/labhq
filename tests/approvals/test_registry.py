"""Risk classes and executors are data: a new action type is a registration."""

from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import (
    PHASE_1_RISK_CLASSES,
    ApprovalService,
    Decision,
    UnknownKeyError,
    default_executors,
    default_risks,
)
from labhq.clock import FakeClock
from labhq.db.enums import ApprovalStatus, RiskClass


@pytest.mark.parametrize("action_type", ["push", "merge", "delete_branch", "create_team"])
def test_phase_1_heavy_action_types(action_type: str) -> None:
    assert default_risks.get(action_type) is RiskClass.HEAVY
    assert PHASE_1_RISK_CLASSES[action_type] is RiskClass.HEAVY


def test_the_engine_executes_push() -> None:
    assert "push" in default_executors


async def test_the_risk_class_comes_from_the_registry(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    service = ApprovalService(sessions, clock=clock)

    approval = await service.request("merge", {"branch": "labhq/task-1"})

    assert approval.risk_class is RiskClass.HEAVY


async def test_a_new_action_type_needs_only_registrations(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    risks, executors = default_risks.copy(), default_executors.copy()
    seen: list[Mapping[str, Any]] = []

    def reprioritise(payload: Mapping[str, Any]) -> dict[str, Any]:
        seen.append(payload)
        return {"priority": payload["priority"]}

    risks.register("set_priority", RiskClass.LIGHT)
    executors.register("set_priority", reprioritise)
    service = ApprovalService(sessions, clock=clock, risks=risks, executors=executors)

    approval = await service.request("set_priority", {"priority": 3})
    executed = await service.approve(
        approval.id, Decision(decided_by="operator", confirmation_kind="cli")
    )

    assert approval.risk_class is RiskClass.LIGHT
    assert executed.status is ApprovalStatus.EXECUTED
    assert executed.execution == {"priority": 3}
    assert seen == [{"priority": 3}]
    assert "set_priority" not in default_risks


async def test_an_unregistered_action_type_cannot_be_requested(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    service = ApprovalService(sessions, clock=clock)

    with pytest.raises(UnknownKeyError, match="reboot"):
        await service.request("reboot", {})

    assert await service.list() == []


def test_a_key_cannot_be_registered_twice_silently() -> None:
    risks = default_risks.copy()

    with pytest.raises(ValueError, match="already registered"):
        risks.register("push", RiskClass.LIGHT)

    risks.register("push", RiskClass.LIGHT, replace=True)
    assert risks.get("push") is RiskClass.LIGHT
    assert default_risks.get("push") is RiskClass.HEAVY
