"""Hand heavy approvals to a gate and settle them from its answers.

One `run_once` pass sends every heavy approval the gate has not seen and polls the ones it
has. The pass is the whole state machine, so a restart loses nothing: the gate request id
lives on the approval row.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals.gates.base import GateAdapter, GateError, GateRequest, GateStatus
from labhq.approvals.service import ApprovalNotPendingError, ApprovalService
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.db.models import Approval, Project, Task

log = logging.getLogger(__name__)

CONFIRMATION = "external_gate"
SENT = "sent"
EXPIRED = "expired"
INSUFFICIENT_PROOF = "insufficient_proof"
# States that stop polling and wait for the owner to re-send.
STALLED = frozenset({EXPIRED, INSUFFICIENT_PROOF})
SUMMARY_LIMIT = 200
# Payload keys that describe the action without carrying a URL, which may hold credentials.
SUMMARY_KEYS = ("branch", "commit")


def summarize(approval: Approval) -> str:
    """One line for the gate's screen: the action and the few facts the owner confirms."""
    parts = [approval.type]
    for key in SUMMARY_KEYS:
        value = approval.payload.get(key)
        if isinstance(value, str) and value:
            parts.append(f"{key}={value[:12] if key == 'commit' else value}")
    line = " ".join(parts) if len(parts) > 1 else f"{approval.type} A{approval.id}"
    return " ".join(line.split())[:SUMMARY_LIMIT]


class GateRelay:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        approvals: ApprovalService,
        gate: GateAdapter,
        *,
        name: str,
        passkey_proofs: frozenset[str],
    ) -> None:
        self._sessions = sessions
        self._approvals = approvals
        self._gate = gate
        self._name = name
        self._proofs = passkey_proofs

    @property
    def decider(self) -> str:
        return f"gate:{self._name}"

    async def run_once(self) -> int:
        """Send and poll once; return how many approvals changed state."""
        changed = 0
        for approval in await self._heavy_pending():
            try:
                if approval.gate is None:
                    changed += await self._send(approval)
                elif approval.gate.get("state") == SENT and approval.gate.get("name") == self._name:
                    changed += await self._poll(approval)
            except GateError as error:
                # One unreachable gate or bad answer is retried on the next pass.
                log.warning("gate %s, approval %s: %s", self._name, approval.id, error)
        return changed

    async def resend(self, approval_id: int) -> None:
        """Forget a stalled request so the next pass sends the approval again."""
        async with self._sessions() as db:
            approval = await db.get_one(Approval, approval_id)
            if approval.status is not ApprovalStatus.PENDING:
                raise ApprovalNotPendingError(
                    f"approval {approval_id} is already {approval.status}"
                )
            if approval.gate is None or approval.gate.get("state") not in STALLED:
                raise GateError(f"approval {approval_id} has no stalled gate request to re-send")
            approval.gate = None
            await db.commit()

    async def _heavy_pending(self) -> list[Approval]:
        async with self._sessions() as db:
            rows = await db.scalars(
                select(Approval)
                .where(
                    Approval.status == ApprovalStatus.PENDING,
                    Approval.risk_class == RiskClass.HEAVY,
                )
                .order_by(Approval.created_at, Approval.id)
            )
            return list(rows)

    async def _send(self, approval: Approval) -> int:
        cwd = await self._project_path(approval)
        request_id = await self._gate.send(GateRequest(summarize(approval), cwd))
        await self._record(
            approval.id, {"name": self._name, "request_id": request_id, "state": SENT}
        )
        return 1

    async def _project_path(self, approval: Approval) -> str:
        if approval.task_id is None:
            return ""
        async with self._sessions() as db:
            task = await db.get(Task, approval.task_id)
            project = await db.get(Project, task.project_id) if task is not None else None
        return project.repo_path if project is not None else ""

    async def _poll(self, approval: Approval) -> int:
        assert approval.gate is not None
        request_id = str(approval.gate["request_id"])
        answer = await self._gate.status(request_id)
        if answer.status is GateStatus.PENDING:
            return 0
        if answer.status is GateStatus.EXPIRED:
            await self._record(approval.id, {**approval.gate, "state": EXPIRED})
            return 1
        if answer.status is GateStatus.DENIED:
            await self._settle(approval.id, approve=False, note=f"denied at {self._name}")
            return 1
        if answer.via not in self._proofs:
            note = f"approved at {self._name} by {answer.via or 'an unnamed proof'}, not a passkey"
            await self._record(
                approval.id, {**approval.gate, "state": INSUFFICIENT_PROOF, "note": note}
            )
            return 1
        await self._settle(approval.id, approve=True, note=f"passkey proof via {answer.via}")
        return 1

    async def _settle(self, approval_id: int, *, approve: bool, note: str) -> None:
        decide = self._approvals.approve if approve else self._approvals.reject
        try:
            await decide(approval_id, decider=self.decider, confirmation=CONFIRMATION, note=note)
        except ApprovalNotPendingError:
            # The owner decided it elsewhere first; the gate's answer is moot.
            log.info("approval %s was decided before the gate answered", approval_id)

    async def _record(self, approval_id: int, gate: dict[str, Any]) -> None:
        async with self._sessions() as db:
            approval = await db.get_one(Approval, approval_id)
            if approval.status is ApprovalStatus.PENDING:
                approval.gate = gate
                await db.commit()
