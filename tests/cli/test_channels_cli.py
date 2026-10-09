"""`labhq channels`: add (with its test message), list, test and remove, with no network."""

import dataclasses

import pytest

from labhq.channels import channel_kinds, copy
from labhq.notify import Message, NotifyError
from tests.cli.conftest import Cli, cli, data_dir

__all__ = ["cli", "data_dir"]


class Recorder:
    def __init__(self) -> None:
        self.sent: list[Message] = []
        self.error: str | None = None

    async def send(self, message: Message) -> None:
        if self.error:
            raise NotifyError(self.error)
        self.sent.append(message)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    ntfy = dataclasses.replace(channel_kinds.get("ntfy"), build=lambda context: recorder)
    monkeypatch.setitem(channel_kinds._entries, "ntfy", ntfy)
    return recorder


def test_a_channel_is_added_tested_listed_and_removed(cli: Cli, recorder: Recorder) -> None:
    cli.ok("init")

    assert "added" in cli.ok("channels", "add", "ntfy", "--name", "phone", "--field", "topic=abc")
    assert [m.title for m in recorder.sent] == [copy.TEST_TITLE]
    (listed,) = cli.ok("channels", "list").splitlines()
    assert listed.split("\t")[1:] == ["phone", "ntfy", "on", "ok"]

    assert "arrived" in cli.ok("channels", "test", "1")
    assert len(recorder.sent) == 2

    cli.ok("channels", "remove", "1")
    assert "no channels" in cli.ok("channels", "list")


def test_a_failed_test_exits_non_zero_and_is_listed_as_failed(cli: Cli, recorder: Recorder) -> None:
    cli.ok("init")
    recorder.error = "ntfy answered HTTP 500"

    result = cli("channels", "add", "ntfy", "--name", "phone", "--field", "topic=abc")

    assert result.exit_code != 0 and "HTTP 500" in result.output
    assert cli.ok("channels", "list").split("\t")[-1].strip() == "failed"


def test_bad_input_and_an_unknown_kind_are_refused(cli: Cli, recorder: Recorder) -> None:
    cli.ok("init")

    assert cli("channels", "add", "pigeon", "--name", "x").exit_code != 0
    assert cli("channels", "add", "ntfy", "--name", "x", "--field", "topic=a b").exit_code != 0
    assert cli("channels", "remove", "9").exit_code != 0
    assert recorder.sent == []
