"""The IT agent's tools: rules with a reason, diagnoses on tickets and fix requests.

Every tool here is marked `read_only`: none of them changes a machine or a repository, so a
read-only agent may hold them (plan §2.2). They record rows a human reads and decides on: a
rule that only notifies or opens a ticket, a comment, a pending heavy approval. Running a
fix stays with #76's executor after a human approved it, and disabling a rule stays with
the owner, so there is no tool for either.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.agenttools import AgentToolSpec, ToolContext
from labhq.agenttools.whoami import NoArguments
from labhq.db.enums import HealthRuleAction
from labhq.db.models import Comment, Host, Project, Task
from labhq.health.intervention import INTERVENTION_ACTION
from labhq.health.manage import add_rule, list_rules, tune_rule
from labhq.health.ssh import DEFAULT_PORT, SshTarget
from labhq.health.tickets import INFRA_PROJECT
from labhq.hierarchy import IT
from labhq.roles.common import Handler, RoleServices, agent_reference, refusing
from labhq.work import WorkError

_REASON = Field(min_length=1, description="Why: what a reader needs to understand it later.")


class AddRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, description="A rule type, e.g. threshold.")
    params: dict[str, Any]
    action: HealthRuleAction
    reason: str = _REASON
    name: str | None = None
    host: int | None = Field(default=None, description="Bind to one host id; default: all.")


class TuneRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: int
    params: dict[str, Any]
    reason: str = _REASON


class WriteDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket: int
    diagnosis: str = Field(min_length=1)


class RequestFix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, description="The host's name.")
    command: str = Field(min_length=1, description="Exactly what the engine runs, by `sh -c`.")
    reason: str = _REASON
    ticket: int


async def ticket(db: AsyncSession, ticket_id: int) -> Task:
    """A task of the infra project: the IT agent writes nowhere else."""
    task = await db.get(Task, ticket_id)
    project_id = task.project_id if task is not None else None
    project = await db.get(Project, project_id) if project_id is not None else None
    if task is None or project is None or project.name != INFRA_PROJECT:
        raise WorkError(f"task {ticket_id} is not an infra ticket")
    return task


async def _add_rule(context: ToolContext, arguments: AddRule) -> str:
    async with context.sessions() as db:
        rule = await add_rule(
            db,
            context.clock,
            rule_type=arguments.type,
            params=arguments.params,
            action=arguments.action,
            reason=arguments.reason,
            created_by=agent_reference(context.agent_id),
            name=arguments.name,
            host_id=arguments.host,
        )
        await db.commit()
    return f"Rule {rule.id} {rule.name!r} added and enabled."


async def _tune_rule(context: ToolContext, arguments: TuneRule) -> str:
    async with context.sessions() as db:
        rule = await tune_rule(
            db,
            context.clock,
            arguments.rule,
            params=arguments.params,
            reason=arguments.reason,
            by=agent_reference(context.agent_id),
        )
        await db.commit()
    return f"Rule {rule.id} tuned."


async def _list_rules(context: ToolContext, arguments: NoArguments) -> str:
    async with context.sessions() as db:
        views = await list_rules(db)
    if not views:
        return "There are no rules."
    lines = []
    for view in views:
        rule = view.rule
        state = "enabled" if rule.enabled else "disabled"
        latest = (
            f"latest incident {view.latest.id} {view.latest.status}"
            if view.latest is not None
            else "no incident yet"
        )
        lines.append(
            f"- {rule.id} {rule.name!r}: {rule.type} -> {rule.action}, {state}, "
            f"host {rule.host_id or 'all'}, by {rule.created_by}, {latest}. "
            f"Params {json.dumps(rule.params, sort_keys=True)}. Reason: {rule.reason}"
        )
    return "\n".join(lines)


async def _write_diagnosis(context: ToolContext, arguments: WriteDiagnosis) -> str:
    async with context.sessions() as db:
        task = await ticket(db, arguments.ticket)
        comment = Comment(
            task_id=task.id,
            author_agent_id=context.agent_id,
            body=arguments.diagnosis,
            created_at=context.clock.now(),
        )
        db.add(comment)
        await db.commit()
    return f"Diagnosis recorded on ticket #{task.id}."


def _ssh_prefix(host: Host) -> str:
    if host.is_local:
        return "local: run commands directly"
    if not host.address or not host.ssh_user:
        return "not reachable: no address or read-only user"
    target = SshTarget.parse(host.address)
    port = "" if target.port == DEFAULT_PORT else f"-p {target.port} "
    return f"ssh {port}{host.ssh_user}@{target.host} <command>"


async def _list_hosts(context: ToolContext, arguments: NoArguments) -> str:
    async with context.sessions() as db:
        hosts = list(await db.scalars(select(Host).order_by(Host.id)))
    if not hosts:
        return "There are no hosts yet."
    return "\n".join(
        f"- {host.id} {host.name} ({host.status}): {_ssh_prefix(host)}" for host in hosts
    )


def it_tools(services: RoleServices) -> list[AgentToolSpec]:
    async def request_fix(context: ToolContext, arguments: RequestFix) -> str:
        async with context.sessions() as db:
            task = await ticket(db, arguments.ticket)
            if await db.scalar(select(Host.id).where(Host.name == arguments.host)) is None:
                raise WorkError(f"no host named {arguments.host!r}")
        approval = await services.approvals(context).request(
            INTERVENTION_ACTION,
            arguments.model_dump(mode="json"),
            task_id=task.id,
            agent_id=context.agent_id,
        )
        return (
            f"Fix requested as A{approval.id} ({approval.risk_class}). Nothing runs until the "
            "owner approves it with a strong confirmation; the result lands on the ticket."
        )

    def spec(
        name: str, description: str, input_model: type[BaseModel], handler: Handler[Any]
    ) -> AgentToolSpec:
        return AgentToolSpec(
            name=name,
            description=description,
            input_model=input_model,
            roles=frozenset({IT}),
            read_only=True,
            handler=refusing(handler),
        )

    return [
        spec(
            "list_rules",
            "List the health rules with their reason and latest incident.",
            NoArguments,
            _list_rules,
        ),
        spec(
            "add_rule",
            "Add a health rule that notifies or opens a ticket; a reason is required.",
            AddRule,
            _add_rule,
        ),
        spec(
            "tune_rule",
            "Replace a rule's params; the new reason explains them.",
            TuneRule,
            _tune_rule,
        ),
        spec(
            "write_diagnosis",
            "Record your diagnosis and proposed fix on an infra ticket.",
            WriteDiagnosis,
            _write_diagnosis,
        ),
        spec(
            "request_fix",
            "Ask the owner to approve one exact command on a host; the "
            "engine runs it after a strong confirmation, never you.",
            RequestFix,
            request_fix,
        ),
        spec(
            "list_hosts",
            "List the watched hosts and how to read from each one.",
            NoArguments,
            _list_hosts,
        ),
    ]
