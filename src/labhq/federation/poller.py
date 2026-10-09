"""The downstream side of the wire: dial out, take orders, post reports.

One `poll_once` is one round trip of each kind. It is safe to repeat: an order is stored once
per upstream id, an acknowledged order is not fetched again, and a report is marked
delivered only after the upstream answered for it.
"""

from dataclasses import dataclass
from types import TracebackType
from typing import Self

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db.models import FederationInbound, FederationReport
from labhq.federation.errors import FederationError, UnauthorizedError
from labhq.federation.inbound import receive_order
from labhq.federation.invites import revoked_locally
from labhq.federation.settings import FederationSettings
from labhq.federation.wire import (
    ORDERS_PATH,
    REPORTS_PATH,
    OrdersBody,
    ReportBody,
    ack_path,
)

# The upstream will never take these reports as they are; retrying changes nothing.
PERMANENT_REFUSALS = frozenset({404, 409, 422})


@dataclass(frozen=True)
class PollResult:
    orders_received: int
    reports_sent: int


class UpstreamClient:
    """An HTTP client for the upstream's federation endpoint, authenticated by the key."""

    def __init__(
        self, settings: FederationSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        if settings.upstream_url is None or settings.upstream_key is None:
            raise FederationError(
                "set LABHQ_FEDERATION_UPSTREAM_URL and LABHQ_FEDERATION_UPSTREAM_KEY first"
            )
        self.key = settings.upstream_key.get_secret_value()
        self._http = httpx.AsyncClient(
            base_url=settings.upstream_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self.key}"},
            timeout=settings.request_timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def orders(self) -> OrdersBody:
        response = await self._http.get(ORDERS_PATH)
        _check(response)
        return OrdersBody.model_validate(response.json())

    async def acknowledge(self, order_id: int) -> None:
        _check(await self._http.post(ack_path(order_id)))

    async def report(self, body: ReportBody) -> httpx.Response:
        response = await self._http.post(REPORTS_PATH, json=body.model_dump(mode="json"))
        if response.status_code not in PERMANENT_REFUSALS:
            _check(response)
        return response


def _check(response: httpx.Response) -> None:
    if response.status_code in {401, 403}:
        raise UnauthorizedError("the upstream refused the key: it is revoked or unknown there")
    if response.is_error:
        raise FederationError(f"the upstream answered {response.status_code}")


async def _unsent(db: AsyncSession) -> list[tuple[FederationReport, FederationInbound]]:
    rows = await db.execute(
        select(FederationReport, FederationInbound)
        .join(FederationInbound, FederationInbound.id == FederationReport.inbound_id)
        # An order taken over A2A is read back by the upstream; there is nothing to post.
        .where(FederationReport.delivered_at.is_(None), FederationInbound.invite_id.is_(None))
        .order_by(FederationReport.inbound_id, FederationReport.seq)
    )
    return [(report, inbound) for report, inbound in rows]


async def poll_once(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    client: UpstreamClient,
    settings: FederationSettings,
) -> PollResult:
    async with sessions() as db:
        if await revoked_locally(db, client.key):
            raise FederationError("this pairing key was revoked here; polling stopped")
    received = 0
    for wire in (await client.orders()).orders:
        async with sessions() as db:
            outcome = await receive_order(
                db,
                clock,
                upstream_name=settings.upstream_name,
                upstream_order_id=wire.id,
                text=wire.text,
                spend_cap_micros=wire.spend_cap_micros,
            )
            await db.commit()
        # Acknowledge only after the order is stored: a crash in between refetches it.
        await client.acknowledge(wire.id)
        received += outcome.new
    sent = 0
    async with sessions() as db:
        for report, inbound in await _unsent(db):
            response = await client.report(
                ReportBody(
                    order_id=inbound.upstream_order_id,
                    seq=report.seq,
                    status=report.status,
                    summary=report.summary,
                    ref=report.ref,
                )
            )
            report.delivered_at = clock.now()
            await db.commit()
            sent += response.is_success
    return PollResult(received, sent)
