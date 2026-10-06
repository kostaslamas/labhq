"""Departments are data: a registry of kinds, with IT migrated to one of them."""

from labhq.approvals.registry import Registry
from labhq.db.models import Agent, Department
from labhq.departments import DepartmentKind, default_kinds
from labhq.departments.kinds import DepartmentKind as Kind
from labhq.guards.readonly import is_read_only
from labhq.it import IT_CONFIG, ensure_it_agent
from labhq.prompts import builtin_registry
from tests.departments.conftest import Research

KINDS = {"it", "general", "research", "marketing", "finance", "content", "admin"}


def test_the_built_in_kinds_are_registered() -> None:
    assert set(default_kinds) >= KINDS
    assert default_kinds.get("it").head_role == "it"
    assert default_kinds.get("research").head_role == "head"


def test_a_new_kind_is_a_registration() -> None:
    kinds = default_kinds.copy()
    kinds.register("legal", DepartmentKind("legal", "You review contracts."))
    assert "legal" in kinds
    assert "legal" not in default_kinds
    assert isinstance(kinds, Registry)
    assert Kind is DepartmentKind


async def test_it_runs_as_a_registered_department_kind(research: Research) -> None:
    org = research.org
    agent = await ensure_it_agent(org.sessions, org.clock, adapters=["fake"], adapter="fake")
    assert (agent.role, agent.reports_to, agent.config) == ("it", org.ceo, IT_CONFIG)
    assert is_read_only(agent.config)
    department = await org.get(Department, agent.department_id or 0)
    assert (department.kind, department.head_agent_id) == ("it", agent.id)
    assert (
        await ensure_it_agent(org.sessions, org.clock, adapters=["fake"], adapter="fake")
        is not None
    )


async def test_the_department_text_reaches_its_agents_and_only_them(research: Research) -> None:
    org = research.org
    head = await org.get(Agent, research.head)
    prompts = builtin_registry()
    text = prompts.assemble(head, None) or ""
    assert "You work in the Research department" in text
    assert "You find, check and summarise facts" in text
    assert "request_outward_action" in text
    ceo = await org.get(Agent, org.ceo)
    assert "department; its folder" not in (prompts.assemble(ceo, None) or "")
