"""`labhq ready`: the database is at the Alembic head and the server answers, or exit 1.

The Docker healthcheck runs it (#69), so it must fail loudly rather than pass on a guess: an
unreadable database, a schema behind the head and a server that does not answer with its
health payload each fail with one line that says which.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import httpx
import typer
from alembic.script import ScriptDirectory
from sqlalchemy.exc import SQLAlchemyError

from labhq.cli.context import fail, load_settings
from labhq.cli.work import MIGRATIONS
from labhq.onboard.database import current_revision
from labhq.settings import DATABASE_FILENAME

HEALTH_PATH = "/api/health"


class NotReadyError(RuntimeError):
    """One readiness condition does not hold; the message says which."""


@dataclass(frozen=True)
class Target:
    host: str
    port: int
    timeout: float


def check_database(_target: Target) -> str:
    settings = load_settings()
    if settings.database_url is None and not (settings.data_dir / DATABASE_FILENAME).exists():
        raise NotReadyError(f"no database in {settings.data_dir}; run `labhq init`")
    head = ScriptDirectory(str(MIGRATIONS)).get_current_head()
    try:
        revision = asyncio.run(current_revision(settings.resolved_database_url))
    except SQLAlchemyError as error:
        raise NotReadyError(f"cannot read the database: {getattr(error, 'orig', error)}") from error
    if revision != head:
        raise NotReadyError(
            f"database schema at {revision}, expected head {head}; run `labhq init`"
        )
    return f"database at head {head}"


def check_server(target: Target) -> str:
    url = f"http://{target.host}:{target.port}{HEALTH_PATH}"
    try:
        response = httpx.get(url, timeout=target.timeout)
    except httpx.HTTPError as error:
        raise NotReadyError(f"server at {url} does not answer: {error}") from error
    if response.status_code != httpx.codes.OK:
        raise NotReadyError(f"server at {url} answered {response.status_code}")
    try:
        version = response.json()["version"]
    except (ValueError, KeyError, TypeError) as error:
        raise NotReadyError(f"server at {url} is not labhq: no version in its answer") from error
    return f"server {version} answers at {url}"


# Every check runs, so one invocation reports every condition that fails.
CHECKS: tuple[Callable[[Target], str], ...] = (check_database, check_server)


def ready(
    host: Annotated[str, typer.Option(help="Host the server answers on.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port the server answers on.")] = 8787,
    timeout: Annotated[
        float, typer.Option(help="Seconds to wait for the server's answer.", min=0.1)
    ] = 5.0,
) -> None:
    """Exit 0 when the database is at the latest migration and the server answers."""
    target = Target(host, port, timeout)
    problems = []
    for check in CHECKS:
        try:
            typer.echo(f"ok: {check(target)}")
        except NotReadyError as error:
            problems.append(str(error))
    if problems:
        fail("; ".join(problems))
