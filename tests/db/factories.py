"""Minimal rows for database tests. Engine issues bring their own fixtures."""

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.models import Agent, Project, Run, Task


async def project_agent_task(session: AsyncSession, clock: Clock) -> tuple[Project, Agent, Task]:
    now = clock.now()
    project = Project(name="demo", repo_path="/srv/demo", created_at=now, updated_at=now)
    session.add(project)
    await session.flush()
    agent = Agent(
        project_id=project.id,
        role="worker",
        title="Worker",
        adapter="fake",
        created_at=now,
        updated_at=now,
    )
    session.add(agent)
    await session.flush()
    task = Task(project_id=project.id, title="First task", created_at=now, updated_at=now)
    session.add(task)
    await session.flush()
    return project, agent, task


async def run_for(session: AsyncSession, clock: Clock, agent: Agent, task: Task) -> Run:
    run = Run(agent_id=agent.id, task_id=task.id, adapter="fake", created_at=clock.now())
    session.add(run)
    await session.flush()
    return run
