"""Acceptance 4: the transport is chosen per node, and a polling node still works."""

from labhq.db.enums import OrderStage
from labhq.db.models import FederationInbound, FederationNode, FederationOrder, Task
from labhq.federation.a2a.sync import sync_once
from labhq.federation.orders import fetch_pending
from tests.federation.a2a.conftest import A2aPairing
from tests.federation.conftest import Pairing


async def test_a_polling_node_is_not_dialled_and_still_polls(pairing: Pairing) -> None:
    a, b = pairing.upstream, pairing.downstream
    await a.call("delegate_task", a.ceo, project="lab", title="By polling")
    await a.drain()

    [order] = await a.all(FederationOrder)
    assert order.status is OrderStage.PENDING  # queueing opened no connection
    assert order.remote_task_id is None
    result = await pairing.poll()

    assert result.orders_received == 1
    [inbound] = await b.all(FederationInbound)
    assert inbound.invite_id is None


async def test_a_node_with_an_a2a_url_hands_polling_no_orders(a2a: A2aPairing) -> None:
    a, b = a2a.upstream, a2a.downstream
    await a.call("delegate_task", a.ceo, project="lab", title="By A2A")
    await a.drain()

    async with a.sessions() as db:
        node = await db.get_one(FederationNode, a2a.node_id)
        pending = await fetch_pending(db, a.clock, node)

    assert pending == []
    assert len(await b.all(FederationInbound)) == 1


async def test_a_polling_node_is_left_alone_by_the_a2a_sync(pairing: Pairing) -> None:
    a = pairing.upstream
    await a.call("delegate_task", a.ceo, project="lab", title="Not by A2A")
    await a.drain()

    result = await sync_once(a.sessions, a.clock, pairing.settings)

    assert (result.orders_sent, result.reports_applied, result.failures) == (0, 0, {})
    assert (await a.all(Task))[0].title == "Not by A2A"
