import pytest

from labhq.db.enums import NotificationStatus
from labhq.notify import Message, NotifyError
from tests.cli.conftest import Cli, cli, data_dir

__all__ = ["cli", "data_dir"]


class Recorder:
    def __init__(self, error: str | None = None) -> None:
        self.sent: list[Message] = []
        self.error = error

    async def send(self, message: Message) -> None:
        if self.error:
            raise NotifyError(self.error)
        self.sent.append(message)


def use(monkeypatch: pytest.MonkeyPatch, notifier: Recorder) -> None:
    monkeypatch.setattr("labhq.cli.notify.build_notifier", lambda *args, **kwargs: notifier)


def test_notify_test_sends_a_test_notification(cli: Cli, monkeypatch: pytest.MonkeyPatch) -> None:
    cli.ok("init")
    recorder = Recorder()
    use(monkeypatch, recorder)

    assert "sent" in cli.ok("notify", "test")
    assert [m.title for m in recorder.sent] == ["labhq test"]
    (row,) = cli.rows("SELECT status, kind FROM notifications")
    assert (row["status"].lower(), row["kind"]) == (NotificationStatus.SENT.value, "test")


def test_notify_test_reports_a_failure_and_exits_non_zero(
    cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli.ok("init")
    use(monkeypatch, Recorder(error="ntfy answered HTTP 500"))

    result = cli("notify", "test")
    assert result.exit_code == 1
    assert "ntfy answered HTTP 500" in result.output


def test_notify_flush_sends_what_is_waiting(cli: Cli, monkeypatch: pytest.MonkeyPatch) -> None:
    cli.ok("init")
    use(monkeypatch, Recorder())
    assert "0 notification(s) sent" in cli.ok("notify", "flush")
