"""A run's system prompt append: role instruction, then output style, from registered sections."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import FakeAdapter, FakeScript, default_registry
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.models import Agent, Task
from labhq.economy.style import AGENT_STYLE, USER_STYLE
from labhq.memory import AgentMemory
from labhq.prompts import (
    OUTPUT_STYLE_POSITION,
    ROLE_POSITION,
    DuplicateRoleError,
    DuplicateSectionError,
    PromptRegistry,
    RoleRegistry,
    builtin_registry,
)
from labhq.runs import RunService
from tests.db.factories import project_agent_task

WORKER_TEXT = "You are a worker. Finish the task in your worktree."


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
def memory(tmp_path: Path) -> AgentMemory:
    # Memory homes stay in the test's directory, never the real data directory.
    return AgentMemory(tmp_path / "agents")


async def run_and_record(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    memory: AgentMemory,
    prompts: PromptRegistry,
    config: dict[str, object] | None = None,
) -> str | None:
    script = FakeScript()
    adapters = default_registry.copy()
    adapters.register("fake", lambda: FakeAdapter(script), replace=True)
    async with sessions() as db:
        _, agent, task = await project_agent_task(db, clock)
        if config is not None:
            await db.execute(update(Agent).where(Agent.id == agent.id).values(config=config))
        await db.commit()
    service = RunService(sessions, clock=clock, registry=adapters, memory=memory, prompts=prompts)
    await service.execute(agent_id=agent.id, task_id=task.id, prompt="go")
    (request,) = script.requests
    return request.system_prompt_append


def worker_roles() -> RoleRegistry:
    roles = RoleRegistry()
    roles.register("worker", WORKER_TEXT)
    return roles


async def test_the_request_carries_the_role_then_the_style(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, memory: AgentMemory
) -> None:
    append = await run_and_record(sessions, clock, memory, builtin_registry(worker_roles()))
    assert append == f"{WORKER_TEXT}\n\n{AGENT_STYLE}"


async def test_the_style_follows_the_agents_recipient(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, memory: AgentMemory
) -> None:
    config = {"output_recipient": "user"}
    append = await run_and_record(sessions, clock, memory, builtin_registry(worker_roles()), config)
    assert append == f"{WORKER_TEXT}\n\n{USER_STYLE}"


async def test_a_role_without_text_gets_the_style_only(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, memory: AgentMemory
) -> None:
    append = await run_and_record(sessions, clock, memory, builtin_registry(RoleRegistry()))
    assert append == AGENT_STYLE


async def test_a_new_section_is_a_registration_placed_by_position(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, memory: AgentMemory
) -> None:
    prompts = builtin_registry(worker_roles())

    def recall(agent: Agent, task: Task | None) -> str:
        return f"Memory for {agent.title} on {task.title if task else 'nothing'}."

    def silent(agent: Agent, task: Task | None) -> None:
        return None

    # Registered last, placed between the role and the style by its position alone.
    prompts.register("memory", recall, position=(ROLE_POSITION + OUTPUT_STYLE_POSITION) // 2)
    prompts.register("silent", silent, position=0)

    append = await run_and_record(sessions, clock, memory, prompts)

    assert append == f"{WORKER_TEXT}\n\nMemory for Worker on First task.\n\n{AGENT_STYLE}"


def test_sections_and_roles_refuse_duplicates() -> None:
    prompts = PromptRegistry()
    prompts.register("a", lambda agent, task: "x", position=1)
    with pytest.raises(DuplicateSectionError):
        prompts.register("a", lambda agent, task: "y", position=2)
    roles = worker_roles()
    with pytest.raises(DuplicateRoleError):
        roles.register("worker", "other")
    with pytest.raises(ValueError, match="non-empty"):
        roles.register("lead", "  ")


def test_no_section_speaking_means_no_append() -> None:
    prompts = PromptRegistry()
    prompts.register("blank", lambda agent, task: "  ", position=1)
    agent = Agent(role="worker", title="W", adapter="fake", config={})
    assert prompts.assemble(agent, None) is None
