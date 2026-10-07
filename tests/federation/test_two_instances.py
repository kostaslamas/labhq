"""Acceptance 2, 3 and 7: an order crosses from A to B's CEO and a pointer report comes back."""

from sqlalchemy import select

from labhq.callcenter.answers.reports import reports
from labhq.db.enums import OrderStatus, TaskStatus, WakeupSource
from labhq.db.models import Comment, FederationOrder, Run, Task, WakeupRequest
from tests.federation.conftest import NODE_NAME, Pairing

ORDER = "Ship the login page.\n\nUse   the *existing* design — no rewording, please."


async def _task_on(instance, title: str) -> Task:
    return next(task for task in await instance.all(Task) if task.title == title)


async def test_an_order_runs_through_both_orgs_and_a_pointer_report_returns(
    pairing: Pairing,
) -> None:
    a, b = pairing.upstream, pairing.downstream

    # A's CEO delegates to the remote manager exactly as to any manager.
    delegated = await a.call(
        "delegate_task",
        a.ceo,
        project="lab",
        title="Ship the login page.",
        description="Use   the *existing* design — no rewording, please.",
    )
    assert "delegated to lab-b (remote)" in delegated
    await a.drain()

    # The remote manager's run only queued the order; the task is still A's to review.
    [order] = await a.all(FederationOrder)
    assert order.text == ORDER
    assert order.status is OrderStatus.PENDING
    task = await _task_on(a, "Ship the login page.")
    assert task.assignee_id == pairing.remote_manager

    # B dials out, stores the order and wakes its CEO with the words unchanged.
    first = await pairing.poll()
    assert (first.orders_received, first.reports_sent) == (1, 0)
    assert (await a.all(FederationOrder))[0].status is OrderStatus.ACKNOWLEDGED
    [wakeup] = await b.all(WakeupRequest)
    assert wakeup.source is WakeupSource.UPSTREAM_ORDER
    await b.drain()
    prompt = b.fake.requests[-1].prompt
    # Whatever the run adds before it (the agent's memory), the order itself is verbatim.
    assert prompt.endswith(f"Order 1 from upstream Lab A. Its words, unchanged:\n\n{ORDER}")

    # B's CEO delegates it down as usual, then reports a pointer.
    assert "delegated to Site manager for order 1" in await b.call(
        "delegate_upstream_order", b.ceo, order=1, project="lab", title="Login page"
    )
    await b.call(
        "report_upstream", b.ceo, order=1, status="ready", summary="Login page is done", ref="T1"
    )
    second = await pairing.poll()
    assert (second.orders_received, second.reports_sent) == (0, 1)

    # A sees it as the remote manager's task report: overview, status and Call Center.
    task = await a.get(Task, task.id)
    assert task.status is TaskStatus.IN_REVIEW
    [comment] = await a.all(Comment)
    assert comment.author_agent_id == pairing.remote_manager
    assert comment.body == f"{NODE_NAME}: Login page is done (see T1 on {NODE_NAME})"
    overview = await a.call("task_overview", a.ceo, task=task.id)
    assert comment.body in overview
    async with a.sessions() as db:
        spoken = await reports(db, a.clock, "lab")
    assert "Login page is done" in spoken

    # A repeated poll changes nothing: the report is applied once.
    third = await pairing.poll()
    assert (third.orders_received, third.reports_sent) == (0, 0)
    assert len(await a.all(Comment)) == 1


async def test_a_blocked_report_marks_the_task_blocked_on_a(pairing: Pairing) -> None:
    a, b = pairing.upstream, pairing.downstream
    await a.call("delegate_task", a.ceo, project="lab", title="Hard job")
    await a.drain()
    await pairing.poll()
    await b.call(
        "report_upstream", b.ceo, order=1, status="blocked", summary="No access to the repo"
    )

    await pairing.poll()

    task = await _task_on(a, "Hard job")
    assert task.status is TaskStatus.BLOCKED


async def test_a_progress_report_adds_a_comment_without_changing_the_status(
    pairing: Pairing,
) -> None:
    a, b = pairing.upstream, pairing.downstream
    await a.call("delegate_task", a.ceo, project="lab", title="Long job")
    await a.drain()
    await pairing.poll()
    await b.call("report_upstream", b.ceo, order=1, status="progress", summary="Half done")

    await pairing.poll()

    task = await _task_on(a, "Long job")
    assert task.status is TaskStatus.IN_PROGRESS
    async with a.sessions() as db:
        bodies = list(await db.scalars(select(Comment.body)))
    assert bodies == [f"{NODE_NAME}: Half done"]


async def test_the_run_that_queues_an_order_is_idempotent(pairing: Pairing) -> None:
    from labhq.federation.orders import queue_order

    a = pairing.upstream
    await a.call("delegate_task", a.ceo, project="lab", title="Once")
    await a.drain()
    [run] = await a.all(Run)

    async with a.sessions() as db:
        again = await queue_order(db, a.clock, run.id)
        await db.commit()

    assert len(await a.all(FederationOrder)) == 1
    assert again.run_id == run.id
