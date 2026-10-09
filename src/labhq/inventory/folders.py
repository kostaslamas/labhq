"""A folder manager: one manager under the CEO for the projects a parent folder holds.

The scan only proposes. The manager is created when the owner approves the light
`create_folder_manager` approval; the folder becomes a project of its own, so the manager has
a place in the hierarchy, and its config lists the projects it looks after.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adoption.record import ensure_ceo, ensure_project
from labhq.adoption.request import refuse_second_manager
from labhq.approvals import ApprovalService
from labhq.clock import Clock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, Approval
from labhq.hierarchy import MANAGER, HierarchySettings
from labhq.inventory.model import FolderProposal
from labhq.settings import Settings

CREATE_FOLDER_MANAGER = "create_folder_manager"
CONFIG_KEY = "folder_manager"


class FolderManagerPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    folder: str
    projects: tuple[str, ...] = Field(min_length=2)


def payload_of(proposal: FolderProposal) -> FolderManagerPayload:
    return FolderManagerPayload(
        folder=str(proposal.folder), projects=tuple(str(p) for p in proposal.projects)
    )


async def propose(approvals: ApprovalService, proposal: FolderProposal) -> Approval:
    """Record the owner's decision to take: nothing exists until it is approved."""
    return await approvals.request(
        CREATE_FOLDER_MANAGER, payload_of(proposal).model_dump(mode="json")
    )


@dataclass(frozen=True)
class FolderManagerEngine:
    clock: Clock = field(default_factory=SystemClock)
    database_url: Callable[[], str] = lambda: Settings().resolved_database_url
    hierarchy: Callable[[], HierarchySettings] = HierarchySettings

    def run(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.create(FolderManagerPayload.model_validate(raw)))

    async def create(self, payload: FolderManagerPayload) -> dict[str, Any]:
        folder = Path(payload.folder)
        engine = create_engine(self.database_url())
        sessions: async_sessionmaker[AsyncSession] = session_factory(engine)
        try:
            async with sessions() as db:
                name = f"{folder.name}-folder"
                await refuse_second_manager(db, name)
                project = await ensure_project(db, self.clock, name, folder)
                ceo = await ensure_ceo(db, self.clock, self.hierarchy().org_adapter)
                now = self.clock.now()
                manager = Agent(
                    project_id=project.id,
                    role=MANAGER,
                    title=f"{folder.name} folder manager",
                    reports_to=ceo.id,
                    adapter=self.hierarchy().org_adapter,
                    config={CONFIG_KEY: {"projects": list(payload.projects)}},
                    status=AgentStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                )
                db.add(manager)
                await db.commit()
                return {"agent_id": manager.id, "project": name, "folder": str(folder)}
        finally:
            await engine.dispose()
