"""What the role tools share: the services they call and how a refusal reaches the agent."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import wraps
from pathlib import Path

from labhq.adapters import UnknownAdapterError
from labhq.adapters import default_registry as default_adapters
from labhq.adoption import AdoptionError, Adoptions
from labhq.agenttools import ToolContext
from labhq.approvals import ApprovalService, UnknownEntryError
from labhq.approvals.service import ApprovalError
from labhq.ceoorg.meetings import meeting_service
from labhq.ceoorg.settings import CeoSettings
from labhq.controlkeys import ControlKeyService, default_control_keys
from labhq.hierarchy import Hierarchy, HierarchySettings
from labhq.meetings import MeetingError, MeetingService
from labhq.settings import Settings
from labhq.work import WorkError

# Errors whose message tells the agent what to change. Anything else is a defect and surfaces.
REFUSALS: tuple[type[Exception], ...] = (
    WorkError,
    ApprovalError,
    UnknownAdapterError,
    UnknownEntryError,
    AdoptionError,
    MeetingError,
    ValueError,
)


def default_approvals(context: ToolContext) -> ApprovalService:
    return ApprovalService(context.sessions, clock=context.clock)


def default_data_dir() -> Path:
    # Read per call, not cached: one process may serve several configurations (tests).
    return Settings().data_dir


def default_browse_roots() -> list[Path]:
    # The roots the web folder picker offers; the CEO sees no more than the owner does.
    # Imported here: `labhq.api` imports the approvals package at load time.
    from labhq.api.settings import get_api_settings

    return list(get_api_settings().repository_browser_roots)


@dataclass(frozen=True)
class RoleServices:
    """How a tool reaches the engine's services from its context; tests replace the parts."""

    approvals: Callable[[ToolContext], ApprovalService] = default_approvals
    hierarchy_settings: Callable[[], HierarchySettings] = HierarchySettings
    adapters: Callable[[], list[str]] = default_adapters.adapter_keys
    ceo_settings: Callable[[], CeoSettings] = CeoSettings
    browse_roots: Callable[[], list[Path]] = default_browse_roots
    data_dir: Callable[[], Path] = default_data_dir
    control_keys: Callable[[ToolContext], ControlKeyService] = lambda context: default_control_keys(
        context.sessions, context.clock
    )

    def hierarchy(self, context: ToolContext) -> Hierarchy:
        return Hierarchy(
            context.sessions,
            clock=context.clock,
            adapters=self.adapters(),
            approvals=self.approvals(context),
            settings=self.hierarchy_settings(),
        )

    def ceo_hierarchy(self, context: ToolContext) -> Hierarchy:
        """The hierarchy as the CEO uses it: a manager it assigns starts active, unasked."""
        settings = self.hierarchy_settings().model_copy(update={"approve_new_agents": False})
        return Hierarchy(
            context.sessions,
            clock=context.clock,
            adapters=self.adapters(),
            approvals=self.approvals(context),
            settings=settings,
        )

    def adoptions(self, context: ToolContext) -> Adoptions:
        return Adoptions(context.sessions, clock=context.clock, approvals=self.approvals(context))

    def meetings(self, context: ToolContext) -> MeetingService:
        return meeting_service(context.sessions, context.clock, self.approvals(context))


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
