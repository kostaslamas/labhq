from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import FakeAdapter, FakeScript, default_registry
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.models import Agent, Task
from labhq.memory import MEMORY_RELATIVE_PATH, AgentMemory, MemorySettings
from labhq.runs import ActiveRun, RunService
from tests.db.factories import project_agent_task

MAX_CHARS = 200


@dataclass
class MemoryWorld:
    service: RunService
    sessions: async_sessionmaker[AsyncSession]
    clock: FakeClock
    memory: AgentMemory
    fake: FakeScript
    project_id: int
    task_ids: list[int]

    async def agent(self, role: str, config: dict[str, Any] | None = None) -> int:
        now = self.clock.now()
        async with self.sessions() as db:
            agent = Agent(
                project_id=self.project_id,
                role=role,
                title=role.title(),
                adapter="fake",
                config=config or {},
                created_at=now,
                updated_at=now,
            )
            db.add(agent)
            await db.commit()
            return agent.id

    async def run(
        self,
        agent_id: int,
        *,
        task_id: int | None = None,
        cwd: Path | None = None,
        writes: str | None = None,
    ) -> ActiveRun:
        """Run to its end; `writes` is what the agent leaves in its memory file meanwhile."""
        active = await self.start(agent_id, task_id=task_id, cwd=cwd)
        if writes is not None:
            write_memory(self.last_cwd(), writes)
        await active.wait()
        return active

    async def start(
        self, agent_id: int, *, task_id: int | None = None, cwd: Path | None = None
    ) -> ActiveRun:
        return await self.service.start(
            agent_id=agent_id, task_id=task_id, prompt="Do the work.", cwd=cwd
        )

    def last_cwd(self) -> Path:
        cwd = self.fake.requests[-1].cwd
        assert cwd is not None
        return cwd

    def last_prompt(self) -> str:
        return self.fake.requests[-1].prompt


def write_memory(cwd: Path, text: str) -> None:
    (cwd / MEMORY_RELATIVE_PATH).write_text(text, encoding="utf-8")


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def world(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, tmp_path: Path
) -> MemoryWorld:
    fake = FakeScript()
    registry = default_registry.copy()
    registry.register("fake", lambda: FakeAdapter(fake), replace=True)
    memory = AgentMemory(tmp_path / "agents", MemorySettings(memory_max_chars=MAX_CHARS))
    now = clock.now()
    async with sessions() as db:
        project, _, task = await project_agent_task(db, clock)
        other = Task(project_id=project.id, title="Second task", created_at=now, updated_at=now)
        db.add(other)
        await db.commit()
        task_ids = [task.id, other.id]
    return MemoryWorld(
        service=RunService(sessions, clock=clock, registry=registry, memory=memory),
        sessions=sessions,
        clock=clock,
        memory=memory,
        fake=fake,
        project_id=project.id,
        task_ids=task_ids,
    )
