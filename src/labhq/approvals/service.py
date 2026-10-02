"""Request, list, approve and reject; execute what was approved.

Agents only request. A decision is claimed with a conditional UPDATE on `pending`, so two
deciders racing on one approval cannot both win and an action can never run twice. Once
approved, the engine runs the executor registered for the action type and records what it
did, or why it failed, on the same row.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals.actions import (
    ExecutorRegistry,
    RiskRegistry,
    default_executors,
    default_risks,
)
from labhq.approvals.confirmations import ConfirmationRegistry, default_confirmations
from labhq.clock import Clock
from labhq.db.enums import ApprovalStatus
from labhq.db.models import Approval


class ApprovalError(RuntimeError):
    pass


class NotPendingError(ApprovalError):
    def __init__(self, approval_id: int) -> None:
        super().__init__(f"approval {approval_id} is not pending")
        self.approval_id = approval_id


class ConfirmationNotAllowedError(ApprovalError):
    pass


@dataclass(frozen=True)
class Decision:
    decided_by: str
    confirmation_kind: str
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.decided_by.strip():
            raise ValueError("a decision needs a decider")


class ApprovalService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        risks: RiskRegistry = default_risks,
        executors: ExecutorRegistry = default_executors,
        confirmations: ConfirmationRegistry = default_confirmations,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._risks = risks
        self._executors = executors
        self._confirmations = confirmations

    async def request(
        self,
        action_type: str,
        payload: Mapping[str, Any],
        *,
        requested_by_agent_id: int | None = None,
        task_id: int | None = None,
    ) -> Approval:
        """Record a pending approval. Nothing runs until a human approves it."""
        approval = Approval(
            type=action_type,
            risk_class=self._risks.get(action_type),
            status=ApprovalStatus.PENDING,
            payload=dict(payload),
            requested_by_agent_id=requested_by_agent_id,
            task_id=task_id,
            created_at=self._clock.now(),
        )
        async with self._sessions() as db:
            db.add(approval)
            await db.commit()
        return approval

    async def get(self, approval_id: int) -> Approval:
        async with self._sessions() as db:
            return await db.get_one(Approval, approval_id, populate_existing=True)

    async def list(self, *, status: ApprovalStatus | None = None) -> list[Approval]:
        query = select(Approval).order_by(Approval.created_at, Approval.id)
        if status is not None:
            query = query.where(Approval.status == status)
        async with self._sessions() as db:
            return list(await db.scalars(query))

    async def approve(self, approval_id: int, decision: Decision) -> Approval:
        """Approve, then execute. Returns the row as `executed` or `execution_failed`."""
        approval = await self._decide(approval_id, decision, ApprovalStatus.APPROVED)
        return await self._execute(approval)

    async def reject(self, approval_id: int, decision: Decision) -> Approval:
        return await self._decide(approval_id, decision, ApprovalStatus.REJECTED)

    async def _decide(
        self, approval_id: int, decision: Decision, outcome: ApprovalStatus
    ) -> Approval:
        kind = self._confirmations.get(decision.confirmation_kind)
        async with self._sessions() as db:
            approval = await db.get_one(Approval, approval_id)
            if not kind.can_resolve(approval.risk_class):
                raise ConfirmationNotAllowedError(
                    f"a {kind.key} confirmation cannot resolve a {approval.risk_class} approval"
                )
            claimed = await db.scalar(
                update(Approval)
                .where(Approval.id == approval_id, Approval.status == ApprovalStatus.PENDING)
                .values(
                    status=outcome,
                    decided_by=decision.decided_by,
                    decided_at=self._clock.now(),
                    confirmation_kind=kind.key,
                    decision_note=decision.note,
                )
                .returning(Approval.id)
            )
            if claimed is None:
                raise NotPendingError(approval_id)
            await db.commit()
            return await db.get_one(Approval, approval_id, populate_existing=True)

    async def _execute(self, approval: Approval) -> Approval:
        try:
            executor = self._executors.get(approval.type)
            execution = await asyncio.to_thread(executor, dict(approval.payload))
            status = ApprovalStatus.EXECUTED
        except Exception as error:
            # A missing executor or any failure is recorded on the row for the operator.
            execution = {"error": f"{type(error).__name__}: {error}"}
            status = ApprovalStatus.EXECUTION_FAILED
        async with self._sessions() as db:
            await db.execute(
                update(Approval)
                .where(Approval.id == approval.id, Approval.status == ApprovalStatus.APPROVED)
                .values(status=status, execution=execution, executed_at=self._clock.now())
            )
            await db.commit()
            return await db.get_one(Approval, approval.id, populate_existing=True)
