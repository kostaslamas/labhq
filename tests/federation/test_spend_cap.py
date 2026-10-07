"""Acceptance 5: A's per-order spend cap is enforced on B, and B's own budgets still apply."""

from sqlalchemy import select, update

from labhq.db.enums import UpstreamStatus, WakeupSource, WakeupStatus
from labhq.db.models import Agent, FederationNode, FederationReport, Run, Task, WakeupRequest
from labhq.federation.cap import CAP_SUMMARY
from labhq.scheduler import Wakeup
from tests.federation.conftest import Instance, Pairing

DOLLAR = 1_000_000


async def _order_on_b(pairing: Pairing, cap_micros: int | None) -> Task:
    """An order from A with a cap, taken by B's CEO and delegated to B's manager."""
    a, b = pairing.upstream, pairing.downstream
    async with a.sessions() as db:
        await db.execute(update(FederationNode).values(spend_cap_micros=cap_micros))
        await db.commit()
    await a.call("delegate_task", a.ceo, project="lab", title="Capped job")
    await a.drain()
    await pairing.poll()
    await b.drain()
    await b.call("delegate_upstream_order", b.ceo, order=1, project="lab", title="Do it")
    return next(task for task in await b.all(Task) if task.title == "Do it")


async def _again(b: Instance, task: Task, key: str) -> None:
    result = await b.scheduler.enqueue(
        Wakeup(
            agent_id=b.manager,
            source=WakeupSource.ASSIGNMENT,
            idempotency_key=key,
            task_id=task.id,
        )
    )
    assert result.request.status is WakeupStatus.PENDING


async def _runs_on(b: Instance, task: Task) -> int:
    async with b.sessions() as db:
        return len(list(await db.scalars(select(Run).where(Run.task_id == task.id))))


async def test_work_past_the_orders_cap_is_refused_and_reported_blocked(
    pairing: Pairing,
) -> None:
    a, b = pairing.upstream, pairing.downstream
    b.fake.cost_usd = 0.6
    task = await _order_on_b(pairing, cap_micros=DOLLAR)

    await b.drain()  # the delegation's own run: $0.60 of $1.00
    assert await _runs_on(b, task) == 1
    await _again(b, task, "second")
    await b.drain()  # $1.20: the cap is reached
    assert await _runs_on(b, task) == 2
    await _again(b, task, "third")
    await b.drain()

    assert await _runs_on(b, task) == 2
    refused = [w for w in await b.all(WakeupRequest) if w.status is WakeupStatus.REFUSED]
    assert [w.idempotency_key for w in refused] == ["third"]
    [blocked] = await b.all(FederationReport)
    assert (blocked.status, blocked.summary) == (UpstreamStatus.BLOCKED, CAP_SUMMARY)

    # The refusal reaches A as a blocked task, so the owner's CEO sees why it stopped.
    await pairing.poll()
    upstream_task = next(t for t in await a.all(Task) if t.title == "Capped job")
    assert upstream_task.status.value == "blocked"
    # A second refusal does not queue a second report.
    await _again(b, task, "fourth")
    await b.drain()
    assert len(await b.all(FederationReport)) == 1


async def test_the_ceo_cannot_delegate_more_of_an_order_that_spent_its_cap(
    pairing: Pairing,
) -> None:
    b = pairing.downstream
    b.fake.cost_usd = 2.0
    await _order_on_b(pairing, cap_micros=DOLLAR)
    await b.drain()

    refusal = await b.call(
        "delegate_upstream_order", b.ceo, order=1, project="lab", title="One more"
    )

    assert refusal == "Refused: order 1 has reached its spend cap"


async def test_an_order_without_a_cap_is_limited_by_b_alone(pairing: Pairing) -> None:
    b = pairing.downstream
    b.fake.cost_usd = 50.0
    task = await _order_on_b(pairing, cap_micros=None)
    await b.drain()
    await _again(b, task, "second")

    await b.drain()

    assert await _runs_on(b, task) == 2


async def test_bs_own_agent_budget_still_applies_under_a_generous_cap(pairing: Pairing) -> None:
    b = pairing.downstream
    b.fake.cost_usd = 0.6
    task = await _order_on_b(pairing, cap_micros=100 * DOLLAR)
    async with b.sessions() as db:
        await db.execute(
            update(Agent).where(Agent.id == b.manager).values(budget_micros=DOLLAR // 2)
        )
        await db.commit()
    await b.drain()  # $0.60 against the manager's $0.50 budget

    result = await b.scheduler.enqueue(
        Wakeup(
            agent_id=b.manager,
            source=WakeupSource.ASSIGNMENT,
            idempotency_key="over-budget",
            task_id=task.id,
        )
    )
    await b.drain()

    assert result.request.status is WakeupStatus.REFUSED
    assert await _runs_on(b, task) == 1
