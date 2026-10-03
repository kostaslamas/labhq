"""`labhq ready` passes only when the schema is at the head and the server answers (#69)."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from labhq.cli.ready import HEALTH_PATH
from labhq.cli.work import MIGRATIONS
from labhq.settings import DATABASE_FILENAME, sqlite_url
from tests.cli.conftest import Cli


class FakeServer:
    """Answers the health path with whatever the test sets; every other path is a 404."""

    def __init__(self) -> None:
        self.status = 200
        self.body: object = {"version": "0.0.0-test"}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                status = owner.status if self.path == HEALTH_PATH else 404
                payload = json.dumps(owner.body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.http.server_address[1]


@pytest.fixture
def server() -> Iterator[FakeServer]:
    fake = FakeServer()
    thread = threading.Thread(target=fake.http.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        fake.http.shutdown()
        fake.http.server_close()
        thread.join()


@pytest.fixture
def closed_port() -> int:
    # Bound and released: nothing listens there for the duration of the test.
    probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = probe.server_address[1]
    probe.server_close()
    return port


def migrate_to(data_dir: Path, revision: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", sqlite_url(data_dir / DATABASE_FILENAME))
    command.upgrade(config, revision)


def ready(cli: Cli, port: int) -> tuple[int, str, str]:
    result = cli("ready", "--port", str(port), "--timeout", "2")
    return result.exit_code, result.stdout, result.stderr


def test_passes_when_the_schema_is_at_head_and_the_server_answers(
    cli: Cli, server: FakeServer
) -> None:
    cli.ok("init")

    code, out, _ = ready(cli, server.port)

    assert code == 0
    head = ScriptDirectory(str(MIGRATIONS)).get_current_head()
    assert f"ok: database at head {head}" in out
    assert "ok: server 0.0.0-test answers" in out


def test_fails_when_the_schema_is_behind_the_head(cli: Cli, server: FakeServer) -> None:
    script = ScriptDirectory(str(MIGRATIONS))
    head = script.get_revision(script.get_current_head())
    assert head is not None
    previous = head.down_revision
    assert isinstance(previous, str)
    migrate_to(cli.data_dir, previous)

    code, out, err = ready(cli, server.port)

    assert code == 1
    assert f"database schema at {previous}, expected head {head.revision}" in err
    # The server check still runs and still reports that it holds.
    assert "ok: server" in out


def test_fails_when_there_is_no_database(cli: Cli, server: FakeServer) -> None:
    code, _, err = ready(cli, server.port)

    assert code == 1
    assert "no database in" in err


def test_fails_when_the_server_does_not_answer(cli: Cli, closed_port: int) -> None:
    cli.ok("init")

    code, out, err = ready(cli, closed_port)

    assert code == 1
    assert "ok: database at head" in out
    assert f"server at http://127.0.0.1:{closed_port}{HEALTH_PATH} does not answer" in err


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (503, {"version": "x"}, "answered 503"),
        (200, {"status": "up"}, "is not labhq"),
        (200, ["version"], "is not labhq"),
    ],
)
def test_fails_when_the_server_is_not_a_healthy_labhq(
    cli: Cli, server: FakeServer, status: int, body: object, reason: str
) -> None:
    cli.ok("init")
    server.status, server.body = status, body

    code, _, err = ready(cli, server.port)

    assert code == 1
    assert reason in err


def test_reports_every_failing_condition_at_once(cli: Cli, closed_port: int) -> None:
    code, _, err = ready(cli, closed_port)

    assert code == 1
    assert err.startswith("error: no database in")
    assert "does not answer" in err
