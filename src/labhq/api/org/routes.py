"""Read and set the one CEO's primary and backup agent kinds."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from labhq.adapters import default_registry
from labhq.adapters.kinds import UnknownAgentChoiceError
from labhq.api.deps import ContextDep
from labhq.api.errors import ApiError
from labhq.auth.routes import SignedIn
from labhq.hierarchy import Hierarchy, HierarchyError
from labhq.usage.plan import agent_kind, fallback_kind

router = APIRouter(tags=["org"])


class CeoAssignment(BaseModel):
    id: int | None
    primary_kind: str | None
    backup_kind: str | None


class SetCeoAssignment(BaseModel):
    primary_kind: str = Field(min_length=1)
    backup_kind: str | None = None


def hierarchy(context: ContextDep) -> Hierarchy:
    return Hierarchy(
        context.sessions,
        clock=context.clock,
        adapters=default_registry.adapter_keys(),
    )


@router.get("/org/ceo")
async def ceo_get(owner: SignedIn, context: ContextDep) -> CeoAssignment:
    """The global CEO assignment, or empty fields before it has been configured."""
    ceo = await hierarchy(context).current_ceo()
    if ceo is None:
        return CeoAssignment(id=None, primary_kind=None, backup_kind=None)
    return CeoAssignment(
        id=ceo.id,
        primary_kind=agent_kind(ceo.adapter, ceo.config),
        backup_kind=fallback_kind(ceo.config),
    )


@router.put("/org/ceo")
async def ceo_put(body: SetCeoAssignment, owner: SignedIn, context: ContextDep) -> CeoAssignment:
    """Configure one CEO for all projects without replacing its identity or team."""
    try:
        ceo = await hierarchy(context).configure_ceo(body.primary_kind, body.backup_kind)
    except (HierarchyError, UnknownAgentChoiceError) as error:
        raise ApiError(422, "ceo_assignment_invalid", str(error)) from None
    return CeoAssignment(
        id=ceo.id,
        primary_kind=agent_kind(ceo.adapter, ceo.config),
        backup_kind=fallback_kind(ceo.config),
    )
