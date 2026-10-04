"""`labhq passkey`: the link on the machine is the first passkey's only way in."""

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from labhq.auth.public_url import load_public_url, store_public_url
from labhq.auth.settings import LOCAL_FALLBACK_URL
from labhq.cli import app
from labhq.cli.serve import remember_public_url

runner = CliRunner()


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cli-data"
    monkeypatch.setenv("LABHQ_DATA_DIR", str(path))
    monkeypatch.delenv("LABHQ_DATABASE_URL", raising=False)
    monkeypatch.delenv("LABHQ_PUBLIC_URL", raising=False)
    assert runner.invoke(app, ["init"]).exit_code == 0
    return path


def test_enroll_prints_a_link_for_the_local_address() -> None:
    result = runner.invoke(app, ["passkey", "enroll"])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith(f"{LOCAL_FALLBACK_URL}/enroll#")


def test_enroll_follows_the_public_url_and_an_explicit_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_PUBLIC_URL", "https://labhq.example.org")
    public = runner.invoke(app, ["passkey", "enroll"])
    assert public.stdout.startswith("https://labhq.example.org/enroll#")
    local = runner.invoke(app, ["passkey", "enroll", "--url", "http://localhost:9000"])
    assert local.stdout.startswith("http://localhost:9000/enroll#")


def test_enroll_refuses_an_address_it_would_not_accept() -> None:
    result = runner.invoke(app, ["passkey", "enroll", "--url", "https://elsewhere.test"])
    assert result.exit_code == 1
    assert "cannot sign in" in result.output


def test_every_link_is_new() -> None:
    first = runner.invoke(app, ["passkey", "enroll"]).stdout
    second = runner.invoke(app, ["passkey", "enroll"]).stdout
    assert first != second


def test_list_says_how_to_start_and_revoke_names_a_missing_passkey() -> None:
    listed = runner.invoke(app, ["passkey", "list"])
    assert listed.exit_code == 0
    assert "labhq passkey enroll" in listed.output
    revoked = runner.invoke(app, ["passkey", "revoke", "7"])
    assert revoked.exit_code == 1
    assert "No passkey has id 7" in revoked.output


def test_enroll_uses_the_address_the_program_persisted(data_dir: Path) -> None:
    store_public_url(data_dir, "https://labhq.example.org")
    result = runner.invoke(app, ["passkey", "enroll"])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("https://labhq.example.org/enroll#")


def test_the_shell_variable_wins_over_the_persisted_address(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_public_url(data_dir, "https://stale.example.org")
    monkeypatch.setenv("LABHQ_PUBLIC_URL", "https://labhq.example.org")
    result = runner.invoke(app, ["passkey", "enroll"])
    assert result.stdout.startswith("https://labhq.example.org/enroll#")


def test_serve_keeps_the_public_url_it_is_given(data_dir: Path) -> None:
    remember_public_url(data_dir, "https://labhq.example.org/ignored/path")
    assert load_public_url(data_dir) == "https://labhq.example.org"


def test_serve_keeps_the_public_url_of_the_shell_variable(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABHQ_PUBLIC_URL", "https://labhq.example.org")
    remember_public_url(data_dir, None)
    assert load_public_url(data_dir) == "https://labhq.example.org"


def test_serve_refuses_an_address_that_is_not_http(data_dir: Path) -> None:
    with pytest.raises(typer.Exit):
        remember_public_url(data_dir, "ftp://labhq.example.org")
    assert load_public_url(data_dir) is None
