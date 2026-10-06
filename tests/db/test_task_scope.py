"""A task belongs to exactly one project or one department, enforced by the database."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.enums import DepartmentStatus
from labhq.db.models import Department, Project, Task


async def _scopes(session: AsyncSession, clock: FakeClock) -> tuple[int, int]:
    now = clock.now()
    project = Project(name="demo", repo_path="/srv/demo", created_at=now, updated_at=now)
    department = Department(
        name="Research",
        kind="research",
        folder="/data/departments/research",
        status=DepartmentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session.add_all([project, department])
    await session.flush()
    return project.id, department.id


def _task(clock: FakeClock, **scope: int | None) -> Task:
    now = clock.now()
    return Task(title="A task", created_at=now, updated_at=now, **scope)


async def test_a_task_in_a_project_or_in_a_department_is_stored(
    session: AsyncSession, clock: FakeClock
) -> None:
    project, department = await _scopes(session, clock)
    session.add_all([_task(clock, project_id=project), _task(clock, department_id=department)])
    await session.flush()


async def test_a_task_cannot_belong_to_both(session: AsyncSession, clock: FakeClock) -> None:
    project, department = await _scopes(session, clock)
    session.add(_task(clock, project_id=project, department_id=department))
    with pytest.raises(IntegrityError, match="CHECK constraint failed: ck_tasks_task_scope"):
        await session.flush()


async def test_a_task_cannot_belong_to_neither(session: AsyncSession, clock: FakeClock) -> None:
    session.add(_task(clock))
    with pytest.raises(IntegrityError, match="CHECK constraint failed: ck_tasks_task_scope"):
        await session.flush()
