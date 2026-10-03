"""`whoami`: the calling agent's role, project and manager. It proves the tool path end to end."""

from pydantic import BaseModel, ConfigDict

from labhq.agenttools.registry import EVERY_ROLE, AgentToolSpec, ToolContext
from labhq.db.models import Agent, Project


class NoArguments(BaseModel):
    # Extra arguments are dropped: the agent is the run's, whatever the model passes.
    model_config = ConfigDict(extra="ignore")


async def whoami(context: ToolContext, arguments: NoArguments) -> str:
    async with context.sessions() as db:
        agent = await db.get_one(Agent, context.agent_id)
        project = await db.get(Project, agent.project_id) if agent.project_id else None
        manager = await db.get(Agent, agent.reports_to) if agent.reports_to else None
    lines = [f"You are agent {agent.id}, {agent.title}, role {agent.role}."]
    lines.append(
        f"Project: {project.name} (id {project.id})."
        if project is not None
        else "Project: none; you work across projects."
    )
    lines.append(
        f"Manager: agent {manager.id}, {manager.title} ({manager.role})."
        if manager is not None
        else "Manager: none."
    )
    return "\n".join(lines)


WHOAMI = AgentToolSpec(
    name="whoami",
    description="Tell who you are in labhq: your agent id, role, project and manager.",
    input_model=NoArguments,
    roles=frozenset({EVERY_ROLE}),
    read_only=True,
    handler=whoami,
)
