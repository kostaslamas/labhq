"""Fetch pending orders, acknowledge one, post a report. Nothing else.

The router is registered `public` because a downstream instance has no owner session; every
route here authenticates the federation key itself, through `FederationNode`, and a key
holds only the scopes it was added with. No route reaches the owner's tools, the CEO's tools,
the approvals or any task beyond the orders given to that node.

Excluded from the OpenAPI schema: the web client is for the owner and never calls these.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Header

from labhq.api.deps import ContextDep
from labhq.api.errors import ApiError
from labhq.db.models import FederationNode
from labhq.federation.errors import FederationError, UnauthorizedError
from labhq.federation.keys import ORDERS, REPORTS
from labhq.federation.nodes import authenticate
from labhq.federation.orders import acknowledge, fetch_pending, receive_report
from labhq.federation.wire import Accepted, OrdersBody, ReportBody, WireOrder

router = APIRouter(prefix="/federation", tags=["federation"], include_in_schema=False)

BEARER = "Bearer "
UNAUTHORIZED_HEADERS = {"WWW-Authenticate": 'Bearer realm="labhq-federation"'}


def node_with_scope(scope: str) -> Callable[..., Awaitable[FederationNode]]:
    """A dependency that resolves the calling node, or answers 401 the same way every time."""

    async def resolve(
        context: ContextDep, authorization: Annotated[str | None, Header()] = None
    ) -> FederationNode:
        key = (
            authorization[len(BEARER) :]
            if authorization and authorization.startswith(BEARER)
            else None
        )
        async with context.sessions() as db:
            try:
                node = await authenticate(db, context.clock, key, scope)
            except UnauthorizedError:
                raise ApiError(
                    401, "unauthorized", "Federation key required.", UNAUTHORIZED_HEADERS
                ) from None
            await db.commit()
            return node

    return resolve


OrdersNode = Annotated[FederationNode, Depends(node_with_scope(ORDERS))]
ReportsNode = Annotated[FederationNode, Depends(node_with_scope(REPORTS))]


@router.get("/orders")
async def federation_orders_get(node: OrdersNode, context: ContextDep) -> OrdersBody:
    """Orders this node has not acknowledged, oldest first."""
    async with context.sessions() as db:
        orders = await fetch_pending(db, context.clock, node)
        body = OrdersBody(
            orders=[
                WireOrder(
                    id=order.id,
                    text=order.text,
                    spend_cap_micros=order.spend_cap_micros,
                    created_at=order.created_at,
                )
                for order in orders
            ]
        )
        await db.commit()
    return body


@router.post("/orders/{order_id}/ack")
async def federation_order_ack_post(
    order_id: int, node: OrdersNode, context: ContextDep
) -> Accepted:
    async with context.sessions() as db:
        try:
            await acknowledge(db, context.clock, node, order_id)
        except FederationError as error:
            raise ApiError(404, "order_not_found", str(error)) from None
        await db.commit()
    return Accepted()


@router.post("/reports")
async def federation_reports_post(
    body: ReportBody, node: ReportsNode, context: ContextDep
) -> Accepted:
    async with context.sessions() as db:
        try:
            applied = await receive_report(
                db,
                context.clock,
                node,
                order_id=body.order_id,
                seq=body.seq,
                status=body.status,
                summary=body.summary,
                ref=body.ref,
            )
        except FederationError as error:
            await db.rollback()
            missing = str(error).startswith("no order")
            raise ApiError(
                404 if missing else 409,
                "order_not_found" if missing else "report_refused",
                str(error),
            ) from None
        await db.commit()
    return Accepted(applied=applied)
