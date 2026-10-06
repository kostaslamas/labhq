"""The CEO's line to the owner: `report_to_owner` and `owner_decision` (issue #170).

The CEO may close or return a root objective only on the owner's own words: the words it
quotes must appear in the owner message that started this run, read from the stored
wakeup (`labhq.ceochat.owner_message_of_run`), never from the model.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from labhq.agenttools import AgentToolSpec, ToolContext
from labhq.ceochat import owner_message_of_run
from labhq.ceoreports import record_report
from labhq.db.models import Task
from labhq.hierarchy import CEO
from labhq.roles.common import refusing
from labhq.work import WorkError
from labhq.work.progress import owner_decide


class ReportToOwner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    refs: list[str] = Field(default_factory=list, max_length=20, description="E.g. T12.")


class OwnerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: int
    decision: Literal["accept", "return"]
    owner_words: str = Field(min_length=1, description="The owner's words, quoted exactly.")


def _squeezed(text: str) -> str:
    return " ".join(text.split())


async def report_to_owner(context: ToolContext, arguments: ReportToOwner) -> str:
    async with context.sessions() as db:
        await record_report(
            db,
            context.clock,
            agent_id=context.agent_id,
            text=arguments.text,
            refs=arguments.refs,
        )
        await db.commit()
    return "Reported to the owner."


async def owner_decision(context: ToolContext, arguments: OwnerDecision) -> str:
    words = _squeezed(arguments.owner_words)
    async with context.sessions() as db:
        said = (
            await owner_message_of_run(db, context.run_id) if context.run_id is not None else None
        )
        if said is None:
            raise WorkError("only a message from the owner can decide a root task")
        if not words or words not in _squeezed(said):
            raise WorkError("owner_words must quote the owner's message exactly")
        task = await db.get(Task, arguments.task)
        if task is None:
            raise WorkError(f"no task {arguments.task}")
        accept = arguments.decision == "accept"
        await owner_decide(db, context.clock, task, accept=accept, feedback=arguments.owner_words)
        await db.commit()
    return f"Task #{task.id} is {task.status}."


def report_tools() -> list[AgentToolSpec]:
    return [
        AgentToolSpec(
            name="report_to_owner",
            description="Report to the owner; it appears in your chat and notifies them.",
            input_model=ReportToOwner,
            roles=frozenset({CEO}),
            read_only=False,
            handler=refusing(report_to_owner),
        ),
        AgentToolSpec(
            name="owner_decision",
            description=(
                "Accept or return a root task when the owner's message decides it; "
                "quote the owner's words."
            ),
            input_model=OwnerDecision,
            roles=frozenset({CEO}),
            read_only=False,
            handler=refusing(owner_decision),
        ),
    ]
