"""What the role tools share: the services they call and how a refusal reaches the agent."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import wraps

from labhq.adapters import UnknownAdapterError
from labhq.adapters import default_registry as default_adapters
from labhq.agenttools import ToolContext
from labhq.approvals import ApprovalService
from labhq.approvals.service import ApprovalError
from labhq.hierarchy import Hierarchy, HierarchySettings
from labhq.work import WorkError

# Errors whose message tells the agent what to change. Anything else is a defect and surfaces.
REFUSALS: tuple[type[Exception], ...] = (WorkError, ApprovalError, UnknownAdapterError, ValueError)


def default_approvals(context: ToolContext) -> ApprovalService:
    return ApprovalService(context.sessions, clock=context.clock)


@dataclass(frozen=True)
class RoleServices:
    """How a tool reaches the engine's services from its context; tests replace the parts."""

    approvals: Callable[[ToolContext], ApprovalService] = default_approvals
    hierarchy_settings: Callable[[], HierarchySettings] = HierarchySettings
    adapters: Callable[[], list[str]] = default_adapters.adapter_keys

    def hierarchy(self, context: ToolContext) -> Hierarchy:
        return Hierarchy(
            context.sessions,
            clock=context.clock,
            adapters=self.adapters(),
            approvals=self.approvals(context),
            settings=self.hierarchy_settings(),
        )


def agent_reference(agent_id: int) -> str:
    """How an agent is named where a string records who did something (`created_by`)."""
    return f"agent:{agent_id}"


type Handler[A] = Callable[[ToolContext, A], Awaitable[str]]


def refusing[A](handler: Handler[A]) -> Handler[A]:
    """Turn an expected refusal into text the model reads and can act on."""

    @wraps(handler)
    async def guarded(context: ToolContext, arguments: A) -> str:
        try:
            return await handler(context, arguments)
        except REFUSALS as error:
            return f"Refused: {error}"

    return guarded
