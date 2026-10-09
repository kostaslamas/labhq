"""A node that cannot be reached, refuses the key, or has no key here does not lose the order."""

import httpx
import pytest

from labhq.db.enums import OrderStage
from labhq.db.models import FederationInbound, FederationOrder
from labhq.federation.errors import FederationError
from labhq.federation.invites import Invites
from labhq.federation.nodes import Nodes
from tests.federation.a2a.conftest import A2aPairing
from tests.federation.conftest import NODE_NAME


class Unreachable(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)


async def test_an_unreachable_node_keeps_the_order_pending_until_the_next_sync(
    a2a: A2aPairing,
) -> None:
    a = a2a.upstream
    live = a2a.link.transport
    a2a.link.transport = Unreachable()  # type: ignore[assignment]
    await a.call("delegate_task", a.ceo, project="lab", title="Later")
    await a.drain()

    [order] = await a.all(FederationOrder)
    assert order.status is OrderStage.PENDING
    assert order.remote_task_id is None
    assert await a2a.downstream.all(FederationInbound) == []

    a2a.link.transport = live
    result = await a2a.sync()

    assert (result.orders_sent, result.failures) == (1, {})
    assert (await a.all(FederationOrder))[0].status is OrderStage.ACKNOWLEDGED
    assert len(await a2a.downstream.all(FederationInbound)) == 1


async def test_a_revoked_invite_stops_the_order_and_says_so(a2a: A2aPairing) -> None:
    a = a2a.upstream
    [invite] = await Invites(a2a.downstream.sessions, clock=a2a.downstream.clock).list()
    await Invites(a2a.downstream.sessions, clock=a2a.downstream.clock).revoke(invite.id)
    await a.call("delegate_task", a.ceo, project="lab", title="Refused")
    await a.drain()

    result = await a2a.sync()

    assert "refused the key" in result.failures[NODE_NAME]
    assert a2a.key not in result.failures[NODE_NAME]
    assert (await a.all(FederationOrder))[0].status is OrderStage.PENDING
    assert await a2a.downstream.all(FederationInbound) == []


async def test_a_node_without_a_key_here_reports_which_setting_to_fill(
    a2a: A2aPairing,
) -> None:
    a2a.link.settings.node_keys.clear()
    await a2a.upstream.call("delegate_task", a2a.upstream.ceo, project="lab", title="No key")
    await a2a.upstream.drain()

    result = await a2a.sync()

    assert "LABHQ_FEDERATION_NODE_KEYS" in result.failures[NODE_NAME]
    assert a2a.link.dialled == []


async def test_a_revoked_node_is_not_sent_anything(a2a: A2aPairing) -> None:
    a = a2a.upstream
    await a.call("delegate_task", a.ceo, project="lab", title="Queued first")
    await a.drain()
    await Nodes(a.sessions, clock=a.clock).revoke(NODE_NAME)
    await a.call("delegate_task", a.ceo, project="lab", title="After revoke")
    await a.drain()
    a2a.link.dialled.clear()

    await a2a.sync()

    assert a2a.link.dialled == []


@pytest.mark.parametrize("bad", ["", "ftp://b.example/a2a", "b.example"])
async def test_an_a2a_url_must_be_http_or_https(a2a: A2aPairing, bad: str) -> None:
    new_key = (await Invites(a2a.downstream.sessions, clock=a2a.downstream.clock).create()).key
    with pytest.raises(FederationError):
        await Nodes(a2a.upstream.sessions, clock=a2a.upstream.clock).add(
            "https://c.example", new_key, project="lab", name="other", a2a_url=bad
        )
