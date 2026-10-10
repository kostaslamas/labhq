"""The Call Center names the scan roots and what was left out, and links to the page."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest

import labhq.mcp.tools  # noqa: F401  (registers every tool)
from labhq.api.public_url import announce_exposure
from labhq.mcp.tools.inventory import scan_scope_tool, sessions_tool
from labhq.mcp.tools.registry import default_registry
from tests.cli.conftest import Cli, cli, data_dir
from tests.inventory import stores_fixture as fx

__all__ = ["cli", "data_dir"]


@pytest.fixture(autouse=True)
def quiet_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("psutil.process_iter", lambda *args, **kwargs: iter(()))
    for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        monkeypatch.delenv(name, raising=False)
    announce_exposure(None)
    yield home
    announce_exposure(None)


def test_without_roots_the_answer_says_machine_wide_and_links_the_page(cli: Cli) -> None:
    cli.ok("init")
    announce_exposure("https://labhq.example.org/")

    answer = asyncio.run(scan_scope_tool())

    assert "όλο το μηχάνημα" in answer
    assert "https://labhq.example.org/session-scan" in answer


def test_with_roots_it_names_them_and_counts_the_rest_without_paths(
    cli: Cli, quiet_machine: Path, tmp_path: Path
) -> None:
    cli.ok("init")
    mine, other = tmp_path / "dev" / "app", tmp_path / "work" / "secret-client"
    mine.mkdir(parents=True)
    other.mkdir(parents=True)
    fx.claude(quiet_machine, mine)
    fx.codex(quiet_machine, other)
    cli.ok("sessions", "roots", "add", str(tmp_path / "dev"))

    answer = asyncio.run(scan_scope_tool())
    spoken = asyncio.run(sessions_tool())

    assert str(tmp_path / "dev") in answer
    assert "Άφησα έξω 1 sessions" in answer
    assert "secret-client" not in answer + spoken
    assert "1 session left out" in spoken
    assert "/session-scan" in answer  # no public address: the page is named, not linked


def test_asking_to_search_another_folder_changes_nothing(cli: Cli, tmp_path: Path) -> None:
    cli.ok("init")
    folder = tmp_path / "Developer"
    folder.mkdir()

    answer = asyncio.run(scan_scope_tool(str(folder)))

    assert str(folder) in answer and "Δεν πρόσθεσα" in answer
    assert "machine-wide" in cli.ok("sessions", "roots")


def test_the_tool_is_read_only_and_says_it_changes_nothing() -> None:
    spec = next(spec for spec in default_registry if spec.name == "session_scope")

    assert spec.annotations is not None and spec.annotations.read_only_hint is True
    assert "changes nothing" in spec.description
