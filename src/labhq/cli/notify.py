"""`labhq notify test` and `labhq notify flush`: try the notifier, send what is waiting."""

import httpx
import typer
from sqlalchemy import select

from labhq.cli.context import Context, execute, fail
from labhq.db.enums import NotificationStatus
from labhq.db.models import Notification
from labhq.notify import Dispatcher, NotifyError, NotifySettings, build_notifier, enqueue

notify_app = typer.Typer(help="Notifications to your phone.", no_args_is_help=True)

HTTP_TIMEOUT_SECONDS = 10.0


async def _flush(context: Context) -> int:
    settings = NotifySettings()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        try:
            notifier = build_notifier(
                settings, client, context.settings.data_dir, sessions=context.sessions
            )
        except NotifyError as error:
            fail(str(error))
        dispatcher = Dispatcher(context.sessions, notifier, clock=context.clock, settings=settings)
        return await dispatcher.dispatch_pending()


@notify_app.command("test")
def test() -> None:
    """Send a test notification through the configured notifier."""

    async def body(context: Context) -> Notification:
        now = context.clock.now()
        async with context.sessions() as db:
            row = await enqueue(
                db,
                kind="test",
                subject="test",
                title="labhq test",
                body="If you read this, notifications work.",
                idempotency_key=f"test:{now.isoformat()}",
                now=now,
            )
            await db.commit()
            row_id = row.id
        await _flush(context)
        async with context.sessions() as db:
            return (await db.scalars(select(Notification).where(Notification.id == row_id))).one()

    row = execute(body)
    if row.status != NotificationStatus.SENT:
        fail(f"test notification not sent: {row.last_error}")
    typer.echo("test notification sent")


@notify_app.command("flush")
def flush() -> None:
    """Send every pending notification that is due."""
    typer.echo(f"{execute(_flush)} notification(s) sent")
