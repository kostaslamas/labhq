"""The A2A endpoint: the agent card and the JSON-RPC route an upstream's orders arrive on (#191).

Two routes, nothing else. The card is public by the protocol's design (it is how a peer finds
the endpoint) and names no owner or CEO tool. The JSON-RPC route refuses every request without
a valid, unrevoked federation key before the SDK's dispatcher sees it, then serves only the
methods `FederationRequestHandler` implements; its tools are orders and reports, the same
surface as the polling endpoint. The router is `public`: an upstream has no owner session.

Excluded from the OpenAPI schema, like the polling endpoint: the web client never calls it.
"""

from typing import Annotated

from a2a.server.context import ServerCallContext
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.server.routes import DefaultServerCallContextBuilder
from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response

from labhq.api.deps import ContextDep
from labhq.api.errors import ApiError
from labhq.federation.a2a.card import build_card
from labhq.federation.a2a.server import INVITE_ID, SCOPES, FederationRequestHandler
from labhq.federation.errors import UnauthorizedError
from labhq.federation.invites import authenticate_invite
from labhq.federation.settings import get_federation_settings

CARD_PATH = "/.well-known/agent-card.json"
BEARER = "Bearer "
UNAUTHORIZED_HEADERS = {"WWW-Authenticate": 'Bearer realm="labhq-federation"'}

a2a_router = APIRouter(prefix="/federation/a2a", tags=["federation"], include_in_schema=False)


class InviteContextBuilder(DefaultServerCallContextBuilder):
    """The SDK's call context, whose version check reads the headers, plus the invite."""

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        context.state[INVITE_ID] = request.state.invite_id
        context.state[SCOPES] = tuple(request.state.invite_scopes)
        return context


@a2a_router.get(CARD_PATH)
async def federation_a2a_card_get(request: Request) -> Response:
    """The agent card. Its interface URL is this endpoint, as the caller reached it."""
    card = build_card(str(request.url_for("federation_a2a_post")))
    return JSONResponse(agent_card_to_dict(card))


@a2a_router.post("")
async def federation_a2a_post(
    request: Request, context: ContextDep, authorization: Annotated[str | None, Header()] = None
) -> Response:
    key = (
        authorization[len(BEARER) :] if authorization and authorization.startswith(BEARER) else None
    )
    async with context.sessions() as db:
        try:
            invite = await authenticate_invite(db, context.clock, key)
        except UnauthorizedError:
            raise ApiError(
                401, "unauthorized", "Federation key required.", UNAUTHORIZED_HEADERS
            ) from None
    request.state.invite_id = invite.id
    request.state.invite_scopes = invite.scopes
    dispatcher = JsonRpcDispatcher(
        FederationRequestHandler(context, get_federation_settings()),
        context_builder=InviteContextBuilder(),
    )
    return await dispatcher.handle_requests(request)
