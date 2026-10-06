"""The org of `tests/roles`, plus a Research department with a head, ready for work."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from labhq.db.models import Agent, Department
from tests.roles.conftest import Org, data_dir, org, sessions  # noqa: F401


@dataclass
class Research:
    org: Org
    department: int
    head: int
    folder: Path


@pytest.fixture
async def research(org: Org) -> Research:  # noqa: F811
    answer = await org.call("create_department", org.ceo, name="Research", kind="research")
    assert answer.startswith("Department Research")
    (department,) = await org.all(Department)
    assert department.head_agent_id is not None
    return Research(org, department.id, department.head_agent_id, Path(department.folder))


async def agents_of(research: Research) -> list[Agent]:
    return [
        agent
        for agent in await research.org.all(Agent)
        if agent.department_id == research.department
    ]
