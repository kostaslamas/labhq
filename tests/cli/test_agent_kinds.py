"""`labhq agent add --kind`: the agent is chosen by name from the registry."""

import json
from pathlib import Path

from tests.cli.conftest import Cli, plain

BASE = ("agent", "add", "--project", "site", "--role", "worker", "--title", "Coder")


def project(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    cli.ok("project", "add", "site", "--repo", str(repo))


def test_a_kind_chooses_the_adapter_and_its_config(cli: Cli, repo: Path) -> None:
    project(cli, repo)

    added = cli.ok(*BASE, "--kind", "codex", "--config", '{"poll_seconds": 1}')
    cli.ok(*BASE, "--kind", "claude")

    assert "tmux" in added
    [codex, sdk] = cli.rows("SELECT adapter, config FROM agents ORDER BY id")
    assert codex["adapter"] == "tmux"
    assert json.loads(codex["config"]) == {"agent": "codex", "poll_seconds": 1}
    assert (sdk["adapter"], json.loads(sdk["config"])) == ("claude", {})


def test_an_unknown_kind_fails_with_the_valid_ones(cli: Cli, repo: Path) -> None:
    project(cli, repo)

    result = cli(*BASE, "--kind", "nope")

    assert result.exit_code == 1
    assert "no agent kind 'nope'" in result.stderr
    assert "codex" in result.stderr
    assert "claude-code" in result.stderr


def test_a_kind_and_an_adapter_that_disagree_fail(cli: Cli, repo: Path) -> None:
    project(cli, repo)

    result = cli(*BASE, "--kind", "codex", "--adapter", "fake")

    assert result.exit_code == 1
    assert "runs on adapter 'tmux'" in result.stderr


def test_without_a_kind_the_adapter_still_defaults_to_the_fake(cli: Cli, repo: Path) -> None:
    project(cli, repo)

    cli.ok(*BASE)

    assert cli.rows("SELECT adapter FROM agents")[0]["adapter"] == "fake"


def test_help_lists_the_kinds(cli: Cli) -> None:
    help_text = " ".join(plain(cli.ok("agent", "add", "--help")).split())

    for name in ("claude", "claude-code", "codex", "gemini", "aider"):
        assert name in help_text
