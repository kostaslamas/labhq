"""Departments at work: the CEO creates and runs them, a head staffs them, members deliver.

The CEO creates a department, appoints its head and delegates to it without asking (issue
#171), within the team cap and the budget ceiling. Anything that reaches outside labhq is a
heavy approval the owner decides with a passkey; no tool here executes one.
"""

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from labhq.agenttools import AgentToolSpec, ToolContext
from labhq.agenttools.whoami import NoArguments
from labhq.approvals.policy import OUTWARD_ACTIONS
from labhq.ceoorg.budget import BudgetScope, set_budget
from labhq.ceoorg.record import record_action
from labhq.db.enums import AgentStatus, TaskStatus
from labhq.db.models import Agent, Comment, Department, Task
from labhq.departments import (
    add_department_task,
    create_department,
    default_kinds,
    department_of,
    find_department,
)
from labhq.hierarchy import CEO, HEAD, ProposedMember, find_ceo
from labhq.roles.common import RoleServices, refusing
from labhq.work import WorkError
from labhq.work.deliverables import DOCUMENT, document_path

OUTWARD_KEYS = tuple(action.key for action in OUTWARD_ACTIONS)
CLOSED = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})


class CreateDepartment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, description="A registered kind, see `list_departments`.")
    head_title: str | None = Field(default=None, max_length=200)
    adapter: str | None = Field(default=None, description="The head's adapter; default the org's.")
    budget_micros: int | None = Field(
        default=None, gt=0, description="Micro-USD, up to the owner's ceiling."
    )


class DelegateDepartmentTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department: str = Field(min_length=1, description="The department's name or numeric id.")
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    deliverable: str = Field(default="report", description="document, report or decision.")
    priority: int = 0


class StaffDepartment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    members: list[ProposedMember] = Field(min_length=1)


class WriteDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: int = Field(description="Your task whose deliverable is a document.")
    content: str = Field(min_length=1)
    name: str = Field(default="document.md", description="A plain file name.")


class RequestOutwardAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(description=f"One of: {', '.join(OUTWARD_KEYS)}.")
    summary: str = Field(min_length=1, description="What would happen, in a sentence.")
    details: str = Field(default="", description="The exact text, recipient, amount or address.")
    task: int | None = Field(default=None, description="The task this is for, if any.")


async def _members(db: Any, department: Department) -> int:
    return (
        await db.scalar(
            select(func.count(Agent.id)).where(
                Agent.department_id == department.id, Agent.status != AgentStatus.RETIRED
            )
        )
        or 0
    )


async def list_departments(context: ToolContext, arguments: NoArguments) -> str:
    async with context.sessions() as db:
        departments = list(await db.scalars(select(Department).order_by(Department.id)))
        lines = []
        for department in departments:
            kind = default_kinds.get(department.kind)
            lines.append(
                f"- {department.name} (id {department.id}, {department.kind}, "
                f"{department.status}): head agent {department.head_agent_id}, "
                f"{await _members(db, department)} agents, delivers "
                f"{', '.join(sorted(kind.deliverables))}"
            )
    kinds = f"Kinds you can create: {', '.join(default_kinds)}."
    return "\n".join([*lines, kinds]) if lines else f"There are no departments. {kinds}"


def department_tools(services: RoleServices) -> list[AgentToolSpec]:
    @refusing
    async def create_department_tool(context: ToolContext, arguments: CreateDepartment) -> str:
        adapter = arguments.adapter or services.hierarchy_settings().org_adapter
        async with context.sessions() as db:
            ceo = await find_ceo(db)
            if ceo is None or ceo.id != context.agent_id:
                raise WorkError("only the CEO creates departments")
            department, head = await create_department(
                db,
                context.clock,
                adapters=services.adapters(),
                ceo=ceo,
                data_dir=services.data_dir(),
                name=arguments.name,
                kind=arguments.kind,
                adapter=adapter,
                head_title=arguments.head_title,
            )
            budget = ""
            if arguments.budget_micros is not None:
                budget = " " + await set_budget(
                    db,
                    context.clock,
                    services.ceo_settings(),
                    caller=context.agent_id,
                    scope=BudgetScope.DEPARTMENT,
                    target=str(department.id),
                    micros=arguments.budget_micros,
                )
            await db.commit()
        await record_action(
            context,
            "create_department",
            {"department": department.id, "kind": department.kind, "head": head.id},
        )
        return (
            f"Department {department.name} (id {department.id}, {department.kind}) created; "
            f"agent {head.id} heads it. Its folder is {department.folder}.{budget} Staff it "
            "with `staff_team`, or let the head do it."
        )

    @refusing
    async def delegate_department_task(
        context: ToolContext, arguments: DelegateDepartmentTask
    ) -> str:
        async with context.sessions() as db:
            department = await find_department(db, arguments.department)
            head = (
                await db.get(Agent, department.head_agent_id) if department.head_agent_id else None
            )
            if head is None or head.status is not AgentStatus.ACTIVE:
                raise WorkError(f"department {department.name} has no active head")
            task = await add_department_task(
                db,
                context.clock,
                department,
                title=arguments.title,
                description=arguments.description,
                deliverable=arguments.deliverable,
                priority=arguments.priority,
                assignee=head.id,
                reason=f"delegated by CEO agent {context.agent_id}",
            )
            await db.commit()
        await record_action(
            context, "delegate_department_task", {"task": task.id, "department": department.id}
        )
        return f"Task #{task.id} delegated to {head.title}; its review will return to you."

    @refusing
    async def staff_department(context: ToolContext, arguments: StaffDepartment) -> str:
        ids = await services.hierarchy(context).staff_team(context.agent_id, arguments.members)
        created = ", ".join(f"{key}=agent {agent_id}" for key, agent_id in ids.items())
        return f"Team created: {created}."

    @refusing
    async def write_document(context: ToolContext, arguments: WriteDocument) -> str:
        async with context.sessions() as db:
            caller = await db.get_one(Agent, context.agent_id)
            task = await db.get(Task, arguments.task)
            if (
                task is None
                or task.department_id is None
                or (task.department_id != caller.department_id)
            ):
                raise WorkError(f"task {arguments.task} is not in your department")
            if task.assignee_id != caller.id:
                raise WorkError(f"task {task.id} is not assigned to you")
            if task.deliverable != DOCUMENT or task.status in CLOSED:
                raise WorkError(f"task {task.id} is a {task.deliverable} task, {task.status}")
            department = await department_of(db, caller)
            folder = department_folder(department)
            target = document_path(folder, task.id, arguments.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(target.write_text, arguments.content, encoding="utf-8")
            task.deliverable_ref = str(target.relative_to(folder))
            task.updated_at = context.clock.now()
            db.add(
                Comment(
                    task_id=task.id,
                    author_agent_id=caller.id,
                    body=f"Saved document {task.deliverable_ref}.",
                    created_at=context.clock.now(),
                )
            )
            await db.commit()
        return f"Document saved as {task.deliverable_ref} in the {department.name} folder."

    @refusing
    async def request_outward_action(context: ToolContext, arguments: RequestOutwardAction) -> str:
        if arguments.action not in OUTWARD_KEYS:
            raise WorkError(f"{arguments.action!r} is not an outward action: {OUTWARD_KEYS}")
        async with context.sessions() as db:
            caller = await db.get_one(Agent, context.agent_id)
            department = await department_of(db, caller)
            if arguments.task is not None:
                task = await db.get(Task, arguments.task)
                if task is None or task.department_id != department.id:
                    raise WorkError(f"task {arguments.task} is not in your department")
        approval = await services.approvals(context).request(
            arguments.action,
            {
                "department": department.id,
                "summary": arguments.summary,
                "details": arguments.details,
            },
            task_id=arguments.task,
            agent_id=context.agent_id,
        )
        return (
            f"Requested as A{approval.id} ({approval.risk_class}). Nothing happens until the "
            "owner approves it with a passkey."
        )

    def spec(
        name: str,
        description: str,
        model: type[BaseModel],
        handler: Any,
        roles: frozenset[str],
        *,
        read_only: bool = False,
    ) -> AgentToolSpec:
        return AgentToolSpec(
            name=name,
            description=description,
            input_model=model,
            roles=roles,
            read_only=read_only,
            handler=handler,
        )

    ceo, head = frozenset({CEO}), frozenset({HEAD})
    # Document and outward tools come from a kind's `default_tools`, not from a role.
    by_kind: frozenset[str] = frozenset()
    return [
        spec(
            "list_departments",
            "List the departments, their heads and the kinds you can create.",
            NoArguments,
            list_departments,
            ceo,
            read_only=True,
        ),
        spec(
            "create_department",
            "Create a non-code department of a registered kind with its head, now, no approval. "
            "An optional budget stays under the owner's ceiling.",
            CreateDepartment,
            create_department_tool,
            ceo,
        ),
        spec(
            "delegate_department_task",
            "Give a department's head an objective with a deliverable: document, report or "
            "decision. Its review returns to you.",
            DelegateDepartmentTask,
            delegate_department_task,
            ceo,
        ),
        spec(
            "staff_department",
            "Create your department's members (workers) now, within the team-size cap.",
            StaffDepartment,
            staff_department,
            head,
        ),
        spec(
            "write_document",
            "Save the document your task delivers into the department folder.",
            WriteDocument,
            write_document,
            by_kind,
        ),
        spec(
            "request_outward_action",
            "Ask the owner to approve something that leaves labhq: an email or message to "
            "a third party, publishing, a payment, a sign-up. It needs a passkey.",
            RequestOutwardAction,
            request_outward_action,
            by_kind,
        ),
    ]


def department_folder(department: Department) -> Path:
    return Path(department.folder)
