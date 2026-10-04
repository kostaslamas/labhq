"""`labhq passkey`: print the one-time enrollment link, list passkeys, revoke one."""

from typing import Annotated

import typer

from labhq.auth import credentials, enrollment
from labhq.auth.errors import AuthError
from labhq.auth.settings import get_auth_settings
from labhq.cli.context import CliError, Context, execute

passkey_app = typer.Typer(help="Passkeys for the web UI.", no_args_is_help=True)


@passkey_app.command("enroll")
def enroll(
    url: Annotated[
        str | None,
        typer.Option(
            help=(
                "Address the browser will use. Default: LABHQ_PUBLIC_URL, else the address "
                "`labhq serve` keeps, else localhost."
            )
        ),
    ] = None,
) -> None:
    """Print a single-use link that enrolls a passkey on the address it names.

    A passkey works only on the host it was made on, so run this once per address you sign in
    from. The link expires after LABHQ_AUTH_ENROLLMENT_TTL_SECONDS (default 10 minutes).
    """
    settings = get_auth_settings()

    async def body(context: Context) -> enrollment.EnrollmentLink:
        async with context.sessions() as db:
            try:
                link = await enrollment.create_link(
                    db, settings, context.clock.now(), url or settings.link_base
                )
            except AuthError as error:
                raise CliError(error.message) from None
            await db.commit()
            return link

    link = execute(body)
    typer.echo(link.url)
    typer.echo(f"Open it once, before {link.expires_at:%Y-%m-%d %H:%M} UTC.", err=True)


@passkey_app.command("list")
def list_passkeys() -> None:
    """List passkeys, newest last."""

    async def body(context: Context) -> list[str]:
        async with context.sessions() as db:
            return [
                f"{row.id}\t{row.name}\t{row.rp_id}\t"
                f"{'revoked' if row.revoked_at else 'active'}\tcreated {row.created_at:%Y-%m-%d}"
                for row in await credentials.all_credentials(db)
            ]

    lines = execute(body)
    if not lines:
        typer.echo("No passkeys yet; run `labhq passkey enroll`.", err=True)
    for line in lines:
        typer.echo(line)


@passkey_app.command("revoke")
def revoke(
    passkey_id: Annotated[int, typer.Argument(help="Id from `labhq passkey list`.")],
) -> None:
    """Revoke a passkey and end the sessions it opened."""

    async def body(context: Context) -> str:
        async with context.sessions() as db:
            try:
                row = await credentials.revoke(db, passkey_id, context.clock.now())
            except AuthError as error:
                raise CliError(error.message) from None
            await db.commit()
            return row.name

    typer.echo(f"revoked passkey {passkey_id} ({execute(body)})")
