"""ntfy and Telegram requests, the persistent topic, and the token staying out of every sink."""

import logging
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.notify import Message, NotifyError, NotifySettings, build_notifier, enqueue
from labhq.notify.topic import load_or_create_topic
from tests.notify.conftest import Outbound, all_rows

TOKEN = "123456:SECRET-token-value"


async def test_ntfy_posts_body_title_priority_and_click_url_to_the_topic(
    outbound: Outbound, tmp_path: Path
) -> None:
    notifier = build_notifier(
        NotifySettings(ntfy_server="https://ntfy.example/", ntfy_topic="abc"),
        outbound.client(),
        tmp_path,
    )
    await notifier.send(Message("Approval", "A7 waits", "https://x.test/a/7"))

    (request,) = outbound.requests
    assert (request.method, str(request.url)) == ("POST", "https://ntfy.example/abc")
    assert request.headers["Title"] == "Approval"
    assert request.headers["Click"] == "https://x.test/a/7"
    assert request.content == b"A7 waits"


async def test_ntfy_encodes_a_non_ascii_title(outbound: Outbound, tmp_path: Path) -> None:
    notifier = build_notifier(NotifySettings(ntfy_topic="abc"), outbound.client(), tmp_path)
    await notifier.send(Message("Έγκριση", "x"))
    assert outbound.requests[0].headers["Title"].startswith("=?UTF-8?B?")


@pytest.mark.posix_only("POSIX file permission bits")
def test_the_generated_topic_is_random_and_kept(tmp_path: Path) -> None:
    first = load_or_create_topic(tmp_path)
    assert load_or_create_topic(tmp_path) == first
    assert load_or_create_topic(tmp_path / "other") != first
    assert (tmp_path / "ntfy_topic").stat().st_mode & 0o077 == 0


async def test_ntfy_without_a_topic_setting_uses_the_kept_topic(
    outbound: Outbound, tmp_path: Path
) -> None:
    notifier = build_notifier(NotifySettings(), outbound.client(), tmp_path)
    await notifier.send(Message("t", "b"))
    assert outbound.requests[0].url.path == "/" + load_or_create_topic(tmp_path)


async def test_telegram_calls_send_message_with_the_chat_id(
    outbound: Outbound, tmp_path: Path
) -> None:
    settings = NotifySettings(kind="telegram", telegram_token=TOKEN, telegram_chat_id="42")
    notifier = build_notifier(settings, outbound.client(), tmp_path)
    await notifier.send(Message("Title", "Body"))

    (request,) = outbound.requests
    assert request.url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert request.content == b'{"chat_id":"42","text":"Title\\nBody"}'


def test_telegram_without_credentials_is_refused(tmp_path: Path) -> None:
    with pytest.raises(NotifyError, match="TELEGRAM_TOKEN"):
        build_notifier(NotifySettings(kind="telegram"), httpx.AsyncClient(), tmp_path)


async def test_the_telegram_token_is_in_no_log_line_and_no_stored_row(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    outbound: Outbound,
    dispatcher_for,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    async with sessions() as db:
        await enqueue(
            db,
            kind="test",
            subject="s",
            title="T",
            body="B",
            idempotency_key="k",
            now=clock.now(),
        )
        await db.commit()
    outbound.statuses = [500, 200]
    dispatcher = dispatcher_for(
        outbound, kind="telegram", telegram_token=TOKEN, telegram_chat_id="42"
    )

    await dispatcher.dispatch_pending()
    stored_after_failure = repr([vars(row) for row in await all_rows(sessions)])
    clock.advance(3600)
    await dispatcher.dispatch_pending()
    stored_after_success = repr([vars(row) for row in await all_rows(sessions)])

    # httpx really logged the request line, and the token is what was rewritten out of it.
    assert any("api.telegram.org/bot<redacted>/sendMessage" in m for m in caplog.messages)
    assert TOKEN not in caplog.text
    assert TOKEN not in stored_after_failure
    assert TOKEN not in stored_after_success
    assert "SECRET" not in repr(NotifySettings(telegram_token=TOKEN))


async def test_a_transport_error_is_reported_without_the_url(
    tmp_path: Path,
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    settings = NotifySettings(kind="telegram", telegram_token=TOKEN, telegram_chat_id="42")
    notifier = build_notifier(settings, client, tmp_path)
    with pytest.raises(NotifyError) as raised:
        await notifier.send(Message("t", "b"))
    assert TOKEN not in str(raised.value)
    assert raised.value.__cause__ is None
