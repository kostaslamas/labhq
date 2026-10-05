"""Each role's run carries its instruction, through the built-in registries (fake adapter)."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import labhq.roles  # noqa: F401  (the registration under test)
from labhq.adapters import FakeAdapter, FakeScript, RunRequest
from labhq.adapters import default_registry as adapters
from labhq.agenttools import default_registry as builtin_tools
from labhq.clock import FakeClock
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, Project, Task
from labhq.economy.style import AGENT_STYLE
from labhq.guards.readonly import PERMISSION_MODE_KEY, READ_ONLY_MODE
from labhq.memory import AgentMemory
from labhq.prompts import default_roles
from labhq.roles import INSTRUCTIONS
from labhq.runs import RunService

IT_CONFIG = {PERMISSION_MODE_KEY: READ_ONLY_MODE}
ROLES = ["ceo", "manager", "lead", "worker", "it"]


def test_every_role_has_its_instruction_registered() -> None:
    assert set(ROLES) == set(INSTRUCTIONS)
    for role in ROLES:
        assert default_roles.instruction(role) == INSTRUCTIONS[role].strip()


def test_the_manager_carries_the_rules_of_adr_0005() -> None:
    text = INSTRUCTIONS["manager"]
    for rule in (".labhq/status.md", "create_task", "Never push or merge", "questions"):
        assert rule in text


def test_the_it_agent_diagnoses_and_never_fixes() -> None:
    text = INSTRUCTIONS["it"]
    for rule in ("never fix", "request_fix", "write_diagnosis", "reason", "cannot disable"):
        assert rule in text


async def run_as(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, tmp_path: Path, role: str
) -> RunRequest:
    script = FakeScript()
    registry = adapters.copy()
    registry.register("fake", lambda: FakeAdapter(script), replace=True)
    now = clock.now()
    async with sessions() as db:
        project = Project(name="site", repo_path="/srv/site", created_at=now, updated_at=now)
        db.add(project)
        await db.flush()
        org_wide = role in {"ceo", "it"}
        agent = Agent(
            project_id=None if org_wide else project.id,
            role=role,
            title=role.upper(),
            adapter="fake",
            config=dict(IT_CONFIG) if role == "it" else {},
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        task = Task(project_id=project.id, title="Work", created_at=now, updated_at=now)
        db.add_all([agent, task])
        await db.commit()
    # Long-lived roles keep memory; their homes stay in this test's directory.
    service = RunService(
        sessions, clock=clock, registry=registry, memory=AgentMemory(tmp_path / "agents")
    )
    await service.execute(agent_id=agent.id, task_id=task.id, prompt="go", cwd=tmp_path)
    (request,) = script.requests
    return request


@pytest.mark.parametrize("role", ROLES)
async def test_each_roles_run_carries_its_instruction(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, tmp_path: Path, role: str
) -> None:
    request = await run_as(sessions, clock, tmp_path, role)
    assert request.system_prompt_append == f"{INSTRUCTIONS[role].strip()}\n\n{AGENT_STYLE}"


@pytest.mark.parametrize(
    ("role", "tools"),
    [
        (
            "ceo",
            {
                "whoami",
                "list_projects",
                "list_agent_sessions",
                "assign_manager",
                "delegate_task",
                "task_overview",
                "review_task",
            },
        ),
        (
            "manager",
            {
                "whoami",
                "propose_team",
                "create_task",
                "assign_task",
                "task_overview",
                "report_task",
                "review_task",
            },
        ),
        (
            "lead",
            {"whoami", "create_task", "assign_task", "task_overview", "report_task", "review_task"},
        ),
        ("worker", {"whoami", "task_overview", "report_task"}),
        (
            "it",
            {
                "whoami",
                "list_rules",
                "add_rule",
                "tune_rule",
                "write_diagnosis",
                "request_fix",
                "list_hosts",
            },
        ),
    ],
)
async def test_each_roles_run_is_served_its_tools(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    tmp_path: Path,
    role: str,
    tools: set[str],
) -> None:
    request = await run_as(sessions, clock, tmp_path, role)
    assert {tool.name for tool in request.agent_tools} == tools
    assert {spec.name for spec in builtin_tools.for_agent(role, request.config)} == tools
