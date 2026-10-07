"""The CEO's two tools for an upstream order: `delegate_upstream_order` and `report_upstream`.

Both act for the run's CEO only. Delegating links the new task to the order, which is how the
order's spend cap finds the work that counts against it. Reporting queues a pointer: a status
and a reference on this instance, never the work itself.
"""

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from labhq.agenttools import AgentToolSpec, ToolContext
from labhq.db.enums import AgentStatus, UpstreamStatus
from labhq.db.models import Agent
from labhq.federation.cap import over_cap
from labhq.federation.errors import FederationError
from labhq.federation.inbound import SUMMARY_CHARS, add_report, find_inbound
from labhq.hierarchy import CEO, MANAGER
from labhq.roles.common import refusing
from labhq.work import add_task, find_project


class DelegateUpstreamOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int = Field(description="The order's number, as the order message names it.")
    project: str = Field(min_length=1, description="Project name or numeric id.")
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    priority: int = 0


class ReportUpstream(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int
    status: UpstreamStatus = Field(
        description="progress: still working. ready: done, awaiting upstream. blocked: stuck."
    )
    summary: str = Field(min_length=1, max_length=SUMMARY_CHARS)
    ref: str = Field(default="", max_length=100, description="Where the result is here, e.g. T12.")


async def delegate_upstream_order(context: ToolContext, arguments: DelegateUpstreamOrder) -> str:
    async with context.sessions() as db:
        inbound = await find_inbound(db, arguments.order)
        if await over_cap(db, inbound):
            raise FederationError(f"order {inbound.id} has reached its spend cap")
        project = await find_project(db, arguments.project)
        manager = await db.scalar(
            select(Agent).where(
                Agent.project_id == project.id,
                Agent.role == MANAGER,
                Agent.status == AgentStatus.ACTIVE,
            )
        )
        if manager is None:
            raise FederationError(f"project {project.name} has no active manager")
        task = await add_task(
            db,
            context.clock,
            project=str(project.id),
            title=arguments.title,
            description=arguments.description,
            priority=arguments.priority,
            assignee=manager.id,
            reason=f"delegated by CEO agent {context.agent_id} for upstream order {inbound.id}",
        )
        inbound.task_ids = [*inbound.task_ids, task.id]
        await db.commit()
    return f"Task #{task.id} delegated to {manager.title} for order {inbound.id}."


async def report_upstream(context: ToolContext, arguments: ReportUpstream) -> str:
    async with context.sessions() as db:
        inbound = await find_inbound(db, arguments.order)
        report = add_report(
            db, context.clock, inbound, arguments.status, arguments.summary, arguments.ref
        )
        await db.commit()
    return f"Reported {report.status} on order {inbound.id} to {inbound.upstream_name}."


def federation_tools() -> list[AgentToolSpec]:
    return [
        AgentToolSpec(
            name="delegate_upstream_order",
            description=(
                "Delegate part of an upstream order to a project's manager. Use this, not "
                "`delegate_task`, for orders from upstream: it counts the work against the "
                "order's spend cap."
            ),
            input_model=DelegateUpstreamOrder,
            roles=frozenset({CEO}),
            read_only=False,
            handler=refusing(delegate_upstream_order),
        ),
        AgentToolSpec(
            name="report_upstream",
            description=(
                "Report on an upstream order: a status and a short pointer to where the result "
                "is on this instance. The upstream reads it, not the work."
            ),
            input_model=ReportUpstream,
            roles=frozenset({CEO}),
            read_only=False,
            handler=refusing(report_upstream),
        ),
    ]
