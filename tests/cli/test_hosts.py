"""`labhq hosts`: add a host after confirming its key, list hosts, and test one collection."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from labhq.cli import app
from labhq.health.ssh import fingerprint
from tests.cli.conftest import Cli, plain
from tests.health.sshd import FakeSshd, running_sshd


@pytest.fixture
def sshd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSshd]:
    with running_sshd() as server:
        key_path = tmp_path / "labhq_ed25519"
        server.client_key.write_private_key(key_path)
        monkeypatch.setenv("LABHQ_SSH_KEY_PATH", str(key_path))
        yield server


def add(sshd: FakeSshd, *extra: str, answer: str | None = None) -> Result:
    address = f"127.0.0.1:{sshd.port}"
    arguments = ["hosts", "add", "nas", "--address", address, "--user", "labhq-ro", *extra]
    return CliRunner().invoke(app, arguments, input=answer)


def test_a_host_is_added_only_after_its_fingerprint_is_confirmed(
    cli: Cli, sshd: FakeSshd, data_dir: Path
) -> None:
    cli.ok("init")
    declined = add(sshd, answer="n\n")
    assert declined.exit_code == 1
    assert fingerprint(sshd.host_key) in declined.stdout
    assert cli.rows("SELECT name FROM hosts") == []
    assert not (data_dir / "known_hosts").exists()

    accepted = add(sshd, "--intervention-user", "labhq-fix", answer="y\n")

    assert accepted.exit_code == 0, accepted.output
    [host] = cli.rows("SELECT name, address, ssh_user, intervention_user FROM hosts")
    assert tuple(host) == ("nas", f"127.0.0.1:{sshd.port}", "labhq-ro", "labhq-fix")
    assert f"[127.0.0.1]:{sshd.port} ssh-ed25519 " in (data_dir / "known_hosts").read_text()
    listed = cli.ok("hosts", "list")
    assert (
        f"nas [ssh] labhq-ro@127.0.0.1:{sshd.port}: unknown, interventions as labhq-fix" in listed
    )


def test_a_fingerprint_given_up_front_must_match(cli: Cli, sshd: FakeSshd) -> None:
    cli.ok("init")
    wrong = add(sshd, "--fingerprint", "SHA256:not-the-key")
    assert wrong.exit_code == 1
    assert "not SHA256:not-the-key" in wrong.stderr

    right = add(sshd, "--fingerprint", fingerprint(sshd.host_key))
    assert right.exit_code == 0, right.output


def test_test_prints_one_collection_without_storing_it(cli: Cli, sshd: FakeSshd) -> None:
    cli.ok("init")
    assert add(sshd, answer="y\n").exit_code == 0

    output = cli.ok("hosts", "test", "nas")

    assert "cpu.percent = 30" in output
    assert "disk.percent [/] = 91" in output
    assert "service.active [nginx] = 0" in output
    assert cli.rows("SELECT id FROM health_samples") == []
    assert {user for user, _ in sshd.commands} == {"labhq-ro"}


def test_test_fails_on_a_changed_host_key(cli: Cli, sshd: FakeSshd) -> None:
    cli.ok("init")
    assert add(sshd, answer="y\n").exit_code == 0
    sshd.change_host_key()

    result = cli("hosts", "test", "nas")

    assert result.exit_code == 1
    assert "does not match" in plain(result.stderr)
    assert sshd.commands == []
