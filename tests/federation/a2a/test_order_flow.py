"""Acceptance 2, 3 and 7: the whole path over A2A with the fake adapter, in one process."""

import pytest
from a2a.types import TaskState
from sqlalchemy import select

from labhq.callcenter.answers.reports import reports
from labhq.db.enums import OrderStage, TaskStatus, WakeupSource
from labhq.db.models import Comment, FederationInbound, FederationOrder, Task, WakeupRequest
from tests.federation.a2a.conftest import UPSTREAM_LABEL, A2aPairing
from tests.federation.conftest import NODE_NAME

ORDER = "Ship the login page.\n\nUse   the *existing* design — no rewording, please."


async def _delegate(a2a: A2aPairing, title: str = "Ship the login page.") -> Task:
    a = a2a.upstream
    await a.call(
        "delegate_task",
        a.ceo,
        project="lab",
        title=title,
        description="Use   the *existing* design — no rewording, please."
        if title[0] == "S"
        else "",
    )
    await a.drain()
    return next(task for task in await a.all(Task) if task.title == title)


async def test_an_order_runs_through_both_orgs_over_a2a(a2a: A2aPairing) -> None:
    a, b = a2a.upstream, a2a.downstream
    task = await _delegate(a2a)

    # The remote manager's run sent the order itself: no poll, and B dialled nothing.
    [order] = await a.all(FederationOrder)
    assert order.text == ORDER
    assert order.status is OrderStage.ACKNOWLEDGED
    assert order.remote_task_id is not None
    assert order.remote_state == "TASK_STATE_SUBMITTED"

    # B's CEO is woken with the words unchanged, labelled as the upstream's.
    [inbound] = await b.all(FederationInbound)
    assert inbound.invite_id is not None
    [wakeup] = await b.all(WakeupRequest)
    assert wakeup.source is WakeupSource.UPSTREAM_ORDER
    await b.drain()
    prompt = b.fake.requests[-1].prompt
    assert prompt.endswith(
        f"Order 1 from upstream {UPSTREAM_LABEL}. Its words, unchanged:\n\n{ORDER}"
    )

    await b.call("delegate_upstream_order", b.ceo, order=1, project="lab", title="Login page")
    await b.call(
        "report_upstream", b.ceo, order=1, status="ready", summary="Login page is done", ref="T1"
    )

    result = await a2a.sync()

    assert (result.orders_sent, result.reports_applied, result.failures) == (0, 1, {})
    # A shows it as the remote manager's pointer report: overview, status and Call Center.
    task = await a.get(Task, task.id)
    assert task.status is TaskStatus.IN_REVIEW
    [comment] = await a.all(Comment)
    assert comment.author_agent_id == a2a.remote_manager
    assert comment.body == f"{NODE_NAME}: Login page is done (see T1 on {NODE_NAME})"
    assert comment.body in await a.call("task_overview", a.ceo, task=task.id)
    async with a.sessions() as db:
        assert "Login page is done" in await reports(db, a.clock, "lab")
    assert (await a.all(FederationOrder))[0].remote_state == "TASK_STATE_COMPLETED"


@pytest.mark.parametrize(
    ("status", "state", "task_status"),
    [
        ("progress", TaskState.TASK_STATE_WORKING, TaskStatus.IN_PROGRESS),
        ("ready", TaskState.TASK_STATE_COMPLETED, TaskStatus.IN_REVIEW),
        ("blocked", TaskState.TASK_STATE_INPUT_REQUIRED, TaskStatus.BLOCKED),
    ],
)
async def test_reports_map_to_task_states_and_back_to_pointer_reports(
    a2a: A2aPairing, status: str, state: TaskState, task_status: TaskStatus
) -> None:
    a, b = a2a.upstream, a2a.downstream
    task = await _delegate(a2a, "Job")
    await b.call("report_upstream", b.ceo, order=1, status=status, summary="Some words", ref="T9")

    # The wire carries the A2A state and the report as an artifact on the same task.
    async with a2a.http(a2a.key) as client:
        answer = await client.post(
            "/api/federation/a2a",
            json={"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "1"}},
        )
    wire = answer.json()["result"]
    assert wire["status"]["state"] == TaskState.Name(state)
    [artifact] = wire["artifacts"]
    assert artifact["parts"][0]["text"] == "Some words"
    assert artifact["metadata"]["labhq.ref"] == "T9"

    await a2a.sync()

    assert (await a.get(Task, task.id)).status is task_status
    async with a.sessions() as db:
        bodies = list(await db.scalars(select(Comment.body)))
    assert bodies == [f"{NODE_NAME}: Some words (see T9 on {NODE_NAME})"]


async def test_a_second_sync_sends_and_applies_nothing_again(a2a: A2aPairing) -> None:
    a, b = a2a.upstream, a2a.downstream
    await _delegate(a2a, "Once")
    await b.call("report_upstream", b.ceo, order=1, status="progress", summary="Half done")

    first = await a2a.sync()
    second = await a2a.sync()

    assert (first.orders_sent, first.reports_applied) == (0, 1)
    assert (second.orders_sent, second.reports_applied) == (0, 0)
    assert len(await a.all(Comment)) == 1
    assert len(await b.all(FederationInbound)) == 1


async def test_a_finished_order_is_not_read_again(a2a: A2aPairing) -> None:
    b = a2a.downstream
    await _delegate(a2a, "Done soon")
    await b.call("report_upstream", b.ceo, order=1, status="ready", summary="Done")
    await a2a.sync()
    assert a2a.link.transport is not None
    a2a.link.transport.methods.clear()

    await a2a.sync()

    [order] = await a2a.upstream.all(FederationOrder)
    assert order.remote_state == "TASK_STATE_COMPLETED"
    assert a2a.link.transport.methods == []
