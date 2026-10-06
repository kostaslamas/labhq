"""`set_budget`: the CEO sets an agent's, project's or department's budget, below the ceiling."""

from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.ceoorg.settings import CeoSettings
from labhq.clock import Clock
from labhq.db.models import Agent, Department, Project
from labhq.departments import find_department
from labhq.hierarchy import CEO
from labhq.money import format_micros
from labhq.work import WorkError, find_agent, find_project


class BudgetScope(StrEnum):
    AGENT = "agent"
    PROJECT = "project"
    DEPARTMENT = "department"


class BudgetRefusedError(WorkError):
    pass


async def set_budget(
    db: AsyncSession,
    clock: Clock,
    settings: CeoSettings,
    *,
    caller: int,
    scope: BudgetScope,
    target: str,
    micros: int,
) -> str:
    """Set the budget and say what changed; the caller commits."""
    ceiling = settings.budget_ceiling_micros
    if ceiling is None:
        raise BudgetRefusedError(
            "the owner has set no budget ceiling (LABHQ_CEO_BUDGET_CEILING_MICROS), "
            "so you cannot set budgets yet"
        )
    if micros <= 0:
        raise BudgetRefusedError("a budget must be more than zero")
    if micros > ceiling:
        raise BudgetRefusedError(
            f"{format_micros(micros)} is above the owner's ceiling of {format_micros(ceiling)}"
        )
    row: Agent | Project | Department
    if scope is BudgetScope.AGENT:
        if not target.isdigit():
            raise BudgetRefusedError("name an agent by its numeric id")
        row = await find_agent(db, int(target))
        if row.id == caller or row.role == CEO:
            raise BudgetRefusedError("the CEO's own budget is the owner's to change")
        label = f"agent {row.id} ({row.title})"
    elif scope is BudgetScope.DEPARTMENT:
        row = await find_department(db, target)
        label = f"department {row.name}"
    else:
        row = await find_project(db, target)
        label = f"project {row.name}"
    before = row.budget_micros
    row.budget_micros = micros
    row.updated_at = clock.now()
    was = "none" if before is None else format_micros(before)
    return f"Budget of {label} is now {format_micros(micros)} (was {was})."
