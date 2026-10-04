"""Request, list, approve and reject; the engine executes what a human approved.

A decision is a conditional UPDATE on a pending row, so two deciders racing on the same
approval cannot both win and an action never executes twice.
"""

import asyncio
from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals.executors import Executor, default_executors
from labhq.approvals.policy import ActionType, ConfirmationKind
from labhq.approvals.policy import default_actions as builtin_actions
from labhq.approvals.policy import default_confirmations as builtin_confirmations
from labhq.approvals.registry import Registry
from labhq.clock import Clock
from labhq.db.enums import ApprovalStatus
from labhq.db.models import Approval
from labhq.notify.outbox import enqueue


class ApprovalError(RuntimeError):
    pass


class ApprovalNotFoundError(ApprovalError, LookupError):
    pass


class ApprovalNotPendingError(ApprovalError):
    pass


class ConfirmationNotAllowedError(ApprovalError, PermissionError):
    pass


class ApprovalService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        actions: Registry[ActionType] = builtin_actions,
        executors: Registry[Executor] = default_executors,
        confirmations: Registry[ConfirmationKind] = builtin_confirmations,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._actions = actions
        self._executors = executors
        self._confirmations = confirmations

    async def request(
        self,
        action_type: str,
        payload: Mapping[str, Any],
        *,
        task_id: int | None = None,
        agent_id: int | None = None,
    ) -> Approval:
        """Record a pending approval. Nothing runs until a human approves it."""
        action = self._actions.get(action_type)
        if action_type in self._executors:
            validate = self._executors.get(action_type).validate
            if validate is not None:
                validate(payload)
        approval = Approval(
            type=action.key,
            risk_class=action.risk_class,
            status=ApprovalStatus.PENDING,
            payload=dict(payload),
            task_id=task_id,
            requested_by_agent_id=agent_id,
            created_at=self._clock.now(),
        )
        async with self._sessions() as db:
            db.add(approval)
            await db.flush()
            await self._announce(db, approval)
            await db.commit()
        return approval

    async def _announce(self, db: AsyncSession, approval: Approval) -> None:
        # Imported here: `labhq.api` imports the approvals package at load time.
        from labhq.api.public_url import approval_link

        # Same transaction as the approval, so a committed approval always has its notification.
        await enqueue(
            db,
            kind="approval_requested",
            subject=f"approval:{approval.id}",
            title=f"Approval needed: {approval.type}",
            body=f"A{approval.id}: {approval.type} ({approval.risk_class}) is waiting for you.",
            idempotency_key=f"approval:{approval.id}",
            click_url=approval_link(approval.id),
            now=self._clock.now(),
        )

    async def get(self, approval_id: int) -> Approval:
        async with self._sessions() as db:
            approval = await db.get(Approval, approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"no approval {approval_id}")
        return approval

    async def list(self, status: ApprovalStatus | None = None) -> list[Approval]:
        query = select(Approval).order_by(Approval.created_at, Approval.id)
        if status is not None:
            query = query.where(Approval.status == status)
        async with self._sessions() as db:
            return list(await db.scalars(query))

    async def approve(
        self,
        approval_id: int,
        *,
        decider: str,
        confirmation: str,
        note: str | None = None,
        idempotency_key: str | None = None,
        within: AsyncSession | None = None,
    ) -> Approval:
        """Approve, then execute through the action's executor when one is registered.

        `within` is a session holding uncommitted proof of the confirmation (a step-up
        assertion). It is committed together with the decision, or rolled back with it.
        """
        approval = await self.get(approval_id)
        kind = self._confirmations.get(confirmation)
        if not kind.can_approve(approval.risk_class):
            raise ConfirmationNotAllowedError(
                f"{confirmation!r} confirmation cannot approve a {approval.risk_class} action"
            )
        await self._decide(
            approval_id,
            ApprovalStatus.APPROVED,
            decider,
            confirmation,
            note,
            idempotency_key=idempotency_key,
            within=within,
        )
        if approval.type not in self._executors:
            return await self.get(approval_id)
        return await self._execute(approval_id, self._executors.get(approval.type))

    async def reject(
        self,
        approval_id: int,
        *,
        decider: str,
        confirmation: str,
        note: str | None = None,
        idempotency_key: str | None = None,
    ) -> Approval:
        # Any registered kind may refuse: saying no never needs strong confirmation.
        self._confirmations.get(confirmation)
        await self._decide(
            approval_id,
            ApprovalStatus.REJECTED,
            decider,
            confirmation,
            note,
            idempotency_key=idempotency_key,
        )
        return await self.get(approval_id)

    async def _decide(
        self,
        approval_id: int,
        status: ApprovalStatus,
        decider: str,
        confirmation: str,
        note: str | None,
        *,
        idempotency_key: str | None = None,
        within: AsyncSession | None = None,
    ) -> None:
        statement = (
            update(Approval)
            .where(Approval.id == approval_id, Approval.status == ApprovalStatus.PENDING)
            .values(
                status=status,
                decided_by=decider,
                decided_at=self._clock.now(),
                confirmation_kind=confirmation,
                decision_note=note,
                decision_key=idempotency_key,
            )
        )
        if within is not None:
            # One transaction with the caller's work, so a spent challenge never outlives a
            # refused decision and a decision never lacks its proof.
            result = cast(CursorResult[Any], await within.execute(statement))
            if result.rowcount == 1:
                await within.commit()
        else:
            async with self._sessions() as db:
                result = cast(CursorResult[Any], await db.execute(statement))
                await db.commit()
        if result.rowcount != 1:
            current = await self.get(approval_id)
            raise ApprovalNotPendingError(f"approval {approval_id} is already {current.status}")

    async def _execute(self, approval_id: int, executor: Executor) -> Approval:
        async with self._sessions() as db:
            approval = await db.get_one(Approval, approval_id)
            try:
                # Executors shell out to git and friends; keep the event loop free meanwhile.
                record = await asyncio.to_thread(executor.run, dict(approval.payload))
            except Exception as error:
                approval.status = ApprovalStatus.EXECUTION_FAILED
                record = {"error": type(error).__name__, "message": str(error)}
            else:
                approval.status = ApprovalStatus.EXECUTED
            approval.execution = record
            approval.executed_at = self._clock.now()
            await db.commit()
        return approval
