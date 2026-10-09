"""Close an idle session: end its process, never in the middle of a turn.

A light `close_session` approval. The conversation stays in the tool's store, so the session
can be resumed later. The check runs twice, when it is requested and again when the owner
approves, because the agent may have started a turn in between; a working agent is left
alone and the approval fails with the reason.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from labhq.adapters.tmux import AgentKinds, default_kinds
from labhq.adoption import AdoptionError
from labhq.adoption.discovery import Processes, all_processes, find_running, is_alive
from labhq.adoption.move import end_process
from labhq.adoption.settings import AdoptionSettings, get_adoption_settings
from labhq.approvals import ApprovalService
from labhq.db.models import Approval
from labhq.inventory.model import SessionInfo, SessionState
from labhq.inventory.probe import Probe, ProcessProbe
from labhq.inventory.settings import InventorySettings, get_inventory_settings

CLOSE_SESSION = "close_session"


class ClosePayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    pid: int = Field(gt=0)
    started_at: float
    folder: str
    session_id: str | None = None


def payload_of(session: SessionInfo) -> ClosePayload:
    if session.pid is None or session.started_at is None:
        raise AdoptionError("only a running session can be closed; a saved one has no process")
    return ClosePayload(
        tool=session.tool,
        pid=session.pid,
        started_at=session.started_at,
        folder=str(session.folder),
        session_id=session.session_id,
    )


def refuse_if_working(
    payload: ClosePayload, kinds: AgentKinds, probe: Probe, processes: Processes
) -> None:
    try:
        agent = find_running(payload.pid, kinds, processes)
    except LookupError:
        raise AdoptionError(f"process {payload.pid} is not running any more") from None
    if agent.started_at != payload.started_at:
        raise AdoptionError(f"process {payload.pid} is no longer the agent that was chosen")
    state = probe.states([agent])[agent.pid]
    if state is SessionState.RUNNING:
        raise AdoptionError(f"{payload.tool} is in the middle of a turn; it was not closed")


@dataclass(frozen=True)
class SessionCloser:
    """Requests the approval and runs it. Tests swap `processes` and `probe`."""

    kinds: AgentKinds = default_kinds
    processes: Processes = all_processes
    probe: Probe | None = None
    settings: InventorySettings = field(default_factory=get_inventory_settings)
    adoption: AdoptionSettings = field(default_factory=get_adoption_settings)

    def _probe(self) -> Probe:
        return self.probe or ProcessProbe(self.kinds, self.settings)

    async def request(self, approvals: ApprovalService, session: SessionInfo) -> Approval:
        payload = payload_of(session)
        await asyncio.to_thread(
            refuse_if_working, payload, self.kinds, self._probe(), self.processes
        )
        return await approvals.request(CLOSE_SESSION, payload.model_dump(mode="json"))

    def run(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        payload = ClosePayload.model_validate(raw)
        refuse_if_working(payload, self.kinds, self._probe(), self.processes)
        end_process(payload.pid, payload.started_at, self.adoption.end_timeout_seconds)
        return {
            "closed": payload.pid,
            "tool": payload.tool,
            "session_id": payload.session_id,
            "alive": is_alive(payload.pid, payload.started_at),
        }
