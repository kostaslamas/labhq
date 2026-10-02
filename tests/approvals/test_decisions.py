"""Decisions: who decided, how it was confirmed, and what may never run."""

from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import (
    ApprovalService,
    ConfirmationKind,
    ConfirmationNotAllowedError,
    Decision,
    NotPendingError,
    UnknownKeyError,
    confirmation_registry,
    risk_registry,
)
from labhq.approvals.actions import ExecutorRegistry
from labhq.approvals.confirmations import CLI
from labhq.clock import FakeClock
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.db.models import Approval

OPERATOR = Decision(decided_by="operator", confirmation_kind="cli", note="looks right")
# How Phase 2 registers a voice client: light only (plan §5, rule 7).
VOICE = ConfirmationKind("voice", frozenset({RiskClass.LIGHT}))
PAYLOAD = {"target": "demo"}


class Recorder:
    def __init__(self) -> None:
        self.calls: list[Mapping[str, Any]] = []

    def __call__(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        return {"done": True}


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def service(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, recorder: Recorder
) -> ApprovalService:
    executors = ExecutorRegistry("executor")
    executors.register("deploy", recorder)
    executors.register("assign", recorder)
    return ApprovalService(
        sessions,
        clock=clock,
        risks=risk_registry({"deploy": RiskClass.HEAVY, "assign": RiskClass.LIGHT}),
        executors=executors,
        confirmations=confirmation_registry(CLI, VOICE),
    )


def assert_decision_recorded(approval: Approval, clock: FakeClock) -> None:
    assert approval.payload == PAYLOAD
    assert approval.risk_class is RiskClass.HEAVY
    assert approval.decided_by == "operator"
    assert approval.confirmation_kind == "cli"
    assert approval.decided_at == clock.now()
    assert approval.decided_at.tzinfo is not None
    assert approval.decision_note == "looks right"


async def test_a_rejected_approval_never_executes(
    service: ApprovalService, recorder: Recorder
) -> None:
    approval = await service.request("deploy", PAYLOAD)

    rejected = await service.reject(approval.id, OPERATOR)

    assert rejected.status is ApprovalStatus.REJECTED
    assert rejected.executed_at is None
    assert rejected.execution is None
    with pytest.raises(NotPendingError):
        await service.approve(approval.id, OPERATOR)
    assert recorder.calls == []
    assert (await service.get(approval.id)).status is ApprovalStatus.REJECTED


async def test_an_approval_row_records_the_full_decision(
    service: ApprovalService, recorder: Recorder, clock: FakeClock
) -> None:
    approval = await service.request("deploy", PAYLOAD)
    clock.advance(60)

    executed = await service.approve(approval.id, OPERATOR)

    assert_decision_recorded(executed, clock)
    assert executed.status is ApprovalStatus.EXECUTED
    assert executed.execution == {"done": True}
    assert recorder.calls == [PAYLOAD]


async def test_a_rejection_row_records_the_full_decision(
    service: ApprovalService, clock: FakeClock
) -> None:
    approval = await service.request("deploy", PAYLOAD)
    clock.advance(60)

    rejected = await service.reject(approval.id, OPERATOR)

    assert_decision_recorded(rejected, clock)


async def test_an_approval_executes_once(service: ApprovalService, recorder: Recorder) -> None:
    approval = await service.request("deploy", PAYLOAD)
    await service.approve(approval.id, OPERATOR)

    with pytest.raises(NotPendingError):
        await service.approve(approval.id, OPERATOR)
    with pytest.raises(NotPendingError):
        await service.reject(approval.id, OPERATOR)
    assert len(recorder.calls) == 1


async def test_a_voice_confirmation_cannot_resolve_a_heavy_approval(
    service: ApprovalService, recorder: Recorder
) -> None:
    approval = await service.request("deploy", PAYLOAD)
    voice = Decision(decided_by="operator", confirmation_kind="voice")

    for decide in (service.approve, service.reject):
        with pytest.raises(ConfirmationNotAllowedError):
            await decide(approval.id, voice)

    assert (await service.get(approval.id)).status is ApprovalStatus.PENDING
    assert recorder.calls == []


async def test_a_voice_confirmation_resolves_a_light_approval(
    service: ApprovalService, recorder: Recorder
) -> None:
    approval = await service.request("assign", PAYLOAD)

    executed = await service.approve(
        approval.id, Decision(decided_by="operator", confirmation_kind="voice")
    )

    assert executed.status is ApprovalStatus.EXECUTED
    assert executed.confirmation_kind == "voice"


async def test_an_unknown_confirmation_kind_is_refused(service: ApprovalService) -> None:
    approval = await service.request("deploy", PAYLOAD)

    with pytest.raises(UnknownKeyError):
        await service.approve(approval.id, Decision(decided_by="x", confirmation_kind="passkey"))

    assert (await service.get(approval.id)).status is ApprovalStatus.PENDING


def test_a_decision_needs_a_decider() -> None:
    with pytest.raises(ValueError, match="decider"):
        Decision(decided_by=" ", confirmation_kind="cli")


async def test_a_failing_executor_is_recorded(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    def explode(payload: Mapping[str, Any]) -> dict[str, Any]:
        raise RuntimeError("remote said no")

    executors = ExecutorRegistry("executor")
    executors.register("deploy", explode)
    service = ApprovalService(
        sessions, clock=clock, risks=risk_registry({"deploy": RiskClass.HEAVY}), executors=executors
    )
    approval = await service.request("deploy", PAYLOAD)

    failed = await service.approve(approval.id, OPERATOR)

    assert failed.status is ApprovalStatus.EXECUTION_FAILED
    assert failed.execution == {"error": "RuntimeError: remote said no"}


async def test_an_approved_type_without_executor_fails_visibly(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    service = ApprovalService(
        sessions,
        clock=clock,
        risks=risk_registry({"deploy": RiskClass.HEAVY}),
        executors=ExecutorRegistry("executor"),
    )
    approval = await service.request("deploy", PAYLOAD)

    failed = await service.approve(approval.id, OPERATOR)

    assert failed.status is ApprovalStatus.EXECUTION_FAILED
    assert failed.execution is not None
    assert "no executor registered" in failed.execution["error"]
