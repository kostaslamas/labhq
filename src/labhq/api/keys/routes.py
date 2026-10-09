"""Control keys for an agent's tmux pane: what it accepts, sending one, and its screen."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from labhq.api.deps import ContextDep
from labhq.api.errors import ApiError
from labhq.auth.routes import SignedIn
from labhq.controlkeys import OWNER_SENDER, ControlKeyError, ControlKeyService, default_control_keys

router = APIRouter(tags=["control-keys"])

STATUS_BY_CODE = {
    "agent_not_found": 404,
    "key_refused": 422,
    "not_permitted": 403,
    "no_pane": 409,
    "headless": 409,
}


def get_key_service(context: ContextDep) -> ControlKeyService:
    return default_control_keys(context.sessions, context.clock)


KeysDep = Annotated[ControlKeyService, Depends(get_key_service)]


class AgentKeys(BaseModel):
    # Empty without a live tmux pane, so the UI shows no buttons for an SDK agent.
    keys: list[str]
    live: bool


class SendKey(BaseModel):
    key: str


class SentKey(BaseModel):
    key: str
    screen: str


class AgentScreen(BaseModel):
    screen: str | None


def _refusal(error: ControlKeyError) -> ApiError:
    return ApiError(STATUS_BY_CODE.get(error.code, 422), error.code, str(error))


@router.get("/agents/{agent_id}/keys")
async def agent_keys_get(agent_id: int, owner: SignedIn, service: KeysDep) -> AgentKeys:
    try:
        support = await service.support(agent_id)
    except ControlKeyError as error:
        raise _refusal(error) from None
    return AgentKeys(keys=support.keys, live=support.live)


@router.post("/agents/{agent_id}/keys")
async def agent_keys_post(
    agent_id: int, body: SendKey, owner: SignedIn, service: KeysDep
) -> SentKey:
    """Send one named key to the agent's live pane; the owner may send any key it lists."""
    try:
        screen = await service.send(OWNER_SENDER, agent_id, body.key)
    except ControlKeyError as error:
        raise _refusal(error) from None
    return SentKey(key=body.key, screen=screen)


@router.get("/agents/{agent_id}/screen")
async def agent_screen_get(agent_id: int, owner: SignedIn, service: KeysDep) -> AgentScreen:
    try:
        return AgentScreen(screen=await service.screen(agent_id))
    except ControlKeyError as error:
        raise _refusal(error) from None
