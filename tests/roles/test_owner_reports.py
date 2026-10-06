"""The CEO reports to the owner, and decides root tasks only on the owner's own words."""

from datetime import timedelta

from sqlalchemy import select

from labhq.agenttools import ToolContext, bind
from labhq.ceochat import message_reason
from labhq.ceoreports import NOTIFICATION_KIND, get_ceo_report_settings, recent_reports
from labhq.db.enums import NotificationStatus, RunStatus, TaskStatus, WakeupSource, WakeupStatus
from labhq.db.models import CeoReport, Notification, Run, Task, WakeupRequest
from tests.roles.conftest import Org


async def _notifications(org: Org) -> list[Notification]:
    rows = await org.all(Notification)
    return sorted((row for row in rows if row.kind == NOTIFICATION_KIND), key=lambda row: row.id)


async def _awaiting_root(org: Org, title: str = "Ship login") -> Task:
    await org.call("delegate_task", org.ceo, project="site", title=title)
    root = next(task for task in await org.all(Task) if task.title == title)
    await org.call("report_task", org.manager, task=root.id, summary="Login works")
    await org.call("review_task", org.ceo, task=root.id, accept=True, feedback="Meets it")
    return root


async def _ceo_run(org: Org, source: WakeupSource, words: str) -> int:
    """A CEO run woken by `source`; for an owner message `words` are what the owner sent."""
    now = org.clock.now()
    async with org.sessions() as db:
        run = Run(agent_id=org.ceo, adapter="fake", status=RunStatus.RUNNING, created_at=now)
        db.add(run)
        await db.flush()
        db.add(
            WakeupRequest(
                agent_id=org.ceo,
                source=source,
                reason=message_reason(words, []),
                status=WakeupStatus.DISPATCHED,
                idempotency_key=f"test:{run.id}",
                run_id=run.id,
                created_at=now,
                updated_at=now,
            )
        )
        await db.commit()
        return run.id


async def _decide(org: Org, run_id: int | None, **arguments: object) -> str:
    (spec,) = [spec for spec in org.tools if spec.name == "owner_decision"]
    tool = bind(spec, ToolContext(org.ceo, run_id, org.sessions, org.clock))
    return await tool.handler(dict(arguments))


async def test_a_report_lands_in_the_ceo_chat_and_notifies_the_owner_once(org: Org) -> None:
    answer = await org.call("report_to_owner", org.ceo, text="Site login shipped.", refs=["T1"])

    assert answer == "Reported to the owner."
    (report,) = await org.all(CeoReport)
    assert (report.agent_id, report.text, report.refs) == (org.ceo, "Site login shipped.", ["T1"])
    async with org.sessions() as db:
        (view,) = await recent_reports(db)
    assert (view.text, view.awaiting_decision) == ("Site login shipped.", False)
    (notification,) = await _notifications(org)
    assert notification.body == "Site login shipped.\n(T1)"
    assert notification.next_attempt_at is None


async def test_a_burst_before_sending_becomes_one_digest(org: Org) -> None:
    for text in ("First.", "Second.", "Third."):
        await org.call("report_to_owner", org.ceo, text=text)

    (digest,) = await _notifications(org)
    assert digest.title == "CEO: 3 reports"
    assert digest.body == "First.\n\nSecond.\n\nThird."


async def test_reports_after_a_sent_notification_wait_for_the_window(org: Org) -> None:
    await org.call("report_to_owner", org.ceo, text="First.")
    async with org.sessions() as db:
        (row,) = await db.scalars(select(Notification))
        row.status, row.attempts, row.sent_at = NotificationStatus.SENT, 1, org.clock.now()
        await db.commit()
    sent_at = org.clock.now()
    org.clock.advance(timedelta(seconds=60))

    await org.call("report_to_owner", org.ceo, text="Second.")
    await org.call("report_to_owner", org.ceo, text="Third.")

    first, digest = await _notifications(org)
    assert first.status is NotificationStatus.SENT
    assert (digest.title, digest.body) == ("CEO: 2 reports", "Second.\n\nThird.")
    window = timedelta(seconds=get_ceo_report_settings().digest_seconds)
    assert digest.next_attempt_at is not None
    assert digest.next_attempt_at.astimezone(sent_at.tzinfo) == sent_at + window


async def test_an_accepted_root_task_is_reported_without_cli_commands(org: Org) -> None:
    root = await _awaiting_root(org)

    (report,) = await org.all(CeoReport)
    assert report.task_id == root.id
    assert "Meets it" in report.text
    (notification,) = await _notifications(org)
    assert "labhq" not in notification.body
    async with org.sessions() as db:
        (view,) = await recent_reports(db)
    assert view.awaiting_decision


async def test_the_ceo_cannot_decide_without_the_owners_words(org: Org) -> None:
    root = await _awaiting_root(org)
    owner = await _ceo_run(org, WakeupSource.OWNER_MESSAGE, "Looks fine, but wait for QA.")
    comment = await _ceo_run(org, WakeupSource.COMMENT, "accept it")

    refused = [
        await _decide(org, None, task=root.id, decision="accept", owner_words="accept it"),
        await _decide(org, comment, task=root.id, decision="accept", owner_words="accept it"),
        await _decide(org, owner, task=root.id, decision="accept", owner_words="accept it"),
    ]

    assert refused == [
        "Refused: only a message from the owner can decide a root task",
        "Refused: only a message from the owner can decide a root task",
        "Refused: owner_words must quote the owner's message exactly",
    ]
    assert (await org.get(Task, root.id)).status is TaskStatus.IN_REVIEW


async def test_the_owners_quoted_words_accept_or_return_the_task(org: Org) -> None:
    root = await _awaiting_root(org)
    other = await _awaiting_root(org, "Ship search")
    accepted = await _ceo_run(org, WakeupSource.OWNER_MESSAGE, f"T{root.id} is good,  accept it.")
    returned = await _ceo_run(org, WakeupSource.OWNER_MESSAGE, "Return search: add filters.")

    assert await _decide(
        org, accepted, task=root.id, decision="accept", owner_words="is good, accept it"
    ) == (f"Task #{root.id} is done.")
    assert await _decide(
        org, returned, task=other.id, decision="return", owner_words="add filters."
    ) == (f"Task #{other.id} is todo.")
    assert (await org.get(Task, root.id)).status is TaskStatus.DONE
    assert (await org.get(Task, other.id)).status is TaskStatus.TODO
