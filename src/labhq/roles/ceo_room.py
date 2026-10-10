"""`propose_decision_room`: the CEO asks the owner to bring a project's manager into the talk.

The CEO only proposes. The room opens when the owner approves its start after seeing the
cost, so this tool has no way to start one (issue #199).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from labhq.agenttools import AgentToolSpec, ToolContext
from labhq.ceoorg.meetings import propose_room
from labhq.ceoorg.record import record_action
from labhq.hierarchy import CEO
from labhq.roles.common import RoleServices, refusing


class ProposeDecisionRoom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1, description="The project's name or numeric id.")
    topic: str | None = Field(default=None, max_length=1000, description="What to settle.")
    proposal_kind: Literal["report", "approval"] | None = Field(
        default=None, description="The proposal under discussion, if the owner pinned one."
    )
    proposal_id: int | None = None


def ceo_room_tools(services: RoleServices) -> list[AgentToolSpec]:
    @refusing
    async def propose_decision_room(context: ToolContext, arguments: ProposeDecisionRoom) -> str:
        if (arguments.proposal_kind is None) != (arguments.proposal_id is None):
            raise ValueError("give both proposal_kind and proposal_id, or neither")
        pinned = (
            (arguments.proposal_kind, arguments.proposal_id)
            if arguments.proposal_kind and arguments.proposal_id is not None
            else None
        )
        meeting = await propose_room(
            services.meetings(context),
            context.sessions,
            caller=context.agent_id,
            project=arguments.project,
            topic=arguments.topic,
            proposal=pinned,
        )
        await record_action(
            context, "propose_decision_room", {"meeting": meeting.id, "project": meeting.project_id}
        )
        return (
            f"Decision room {meeting.id} proposed. It opens only when the owner approves it, "
            "after seeing its cost. Tell the owner you asked."
        )

    return [
        AgentToolSpec(
            name="propose_decision_room",
            description=(
                "Ask the owner to open a decision room with a project's manager and you, about "
                "the proposal they pinned. You cannot start it; the owner approves it and sees "
                "the cost."
            ),
            input_model=ProposeDecisionRoom,
            roles=frozenset({CEO}),
            read_only=False,
            handler=propose_decision_room,
        )
    ]
