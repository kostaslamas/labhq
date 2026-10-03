"""The IT department over the role tests' org; fix requests go to a spy executor."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest

from labhq.approvals.executors import Executor, Payload
from labhq.health.intervention import INTERVENTION_ACTION, InterventionPayload
from labhq.hierarchy import HierarchySettings
from labhq.it import ItDepartment, ItSettings, ensure_it_agent
from tests.roles.conftest import Org, data_dir, org, sessions

__all__ = ["data_dir", "org", "sessions"]


@dataclass
class SpyExecutor:
    """Stands in for #76's executor: it records a call, so a test can prove there was none."""

    calls: list[Payload]

    def run(self, payload: Payload) -> dict[str, Any]:
        self.calls.append(payload)
        return {}


@pytest.fixture
def intervention(org: Org) -> SpyExecutor:
    spy = SpyExecutor([])
    org.executors.register(
        INTERVENTION_ACTION,
        Executor(run=spy.run, validate=InterventionPayload.model_validate),
        replace=True,
    )
    return spy


type DepartmentFactory = Callable[..., Awaitable[ItDepartment]]


async def start_it_agent(org: Org) -> int:
    agent = await ensure_it_agent(
        org.sessions,
        org.clock,
        adapters=["fake"],
        hierarchy=HierarchySettings(org_adapter="fake"),
    )
    return agent.id


@pytest.fixture
def department(org: Org) -> DepartmentFactory:
    """The department with its agent started, as `labhq it start` leaves it."""

    async def build(**settings: Any) -> ItDepartment:
        await start_it_agent(org)
        return ItDepartment(org.sessions, org.clock, ItSettings(**settings))

    return build
