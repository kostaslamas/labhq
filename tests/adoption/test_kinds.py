"""Every CLI entry can be adopted: a `continue` template, a rules route and its source."""

import json
import sys
from pathlib import Path

import pytest

from labhq.adapters.tmux import AgentKind, RulesInjection, default_kinds
from labhq.adoption.rules import appends, rules_text, sends
from labhq.adoption.session import AdoptedSession, continue_argv

CLIS = ("claude-code", "codex", "gemini", "aider")


@pytest.fixture
def session(tmp_path: Path) -> AdoptedSession:
    return AdoptedSession("adopted-1", tmp_path / "checkout", tmp_path / "state")


@pytest.mark.parametrize("name", CLIS)
def test_each_cli_records_how_it_continues_and_where_that_was_checked(name: str) -> None:
    kind = default_kinds.get(name)

    assert kind.continue_ is not None
    assert "checked 2026-10-03" in kind.continue_source
    if appends(kind):
        assert any("{rules" in word for word in kind.rules_words)
    if sends(kind):
        # First-message rules go again after compaction, so its notice must be recognised.
        assert kind.compaction_pattern


def argv_of(name: str, session: AdoptedSession, sandbox: tuple[str, ...] = ()) -> list[str]:
    return continue_argv(default_kinds.get(name), session, python=sys.executable, sandbox=sandbox)


def test_claude_continues_with_the_rules_and_labhq_statusline_at_start(
    session: AdoptedSession,
) -> None:
    argv = argv_of("claude-code", session)

    assert argv[0] == "claude" and "--continue" in argv
    assert argv[argv.index("--append-system-prompt") + 1] == rules_text()
    # A resumed conversation reuses its recorded system prompt unless the snapshot is off.
    assert argv[argv.index("--system-prompt-snapshot") + 1] == "off"
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert str(session.statusline_path) in settings["statusLine"]["command"]
    assert settings["hooks"]["PreToolUse"]


def test_first_message_kinds_carry_no_rules_words(session: AdoptedSession) -> None:
    argv = argv_of("gemini", session)

    assert argv == list(default_kinds.get("gemini").continue_ or ())
    assert default_kinds.get("gemini").rules_injection is RulesInjection.FIRST_MESSAGE


def test_aider_reads_the_rules_file_with_every_request(session: AdoptedSession) -> None:
    argv = argv_of("aider", session)

    assert argv[argv.index("--read") + 1] == str(session.cwd / ".labhq" / "rules.md")


def test_a_configured_sandbox_wraps_the_command(session: AdoptedSession) -> None:
    argv = argv_of("codex", session, sandbox=("bwrap", "--die-with-parent", "--"))

    assert argv[:4] == ["bwrap", "--die-with-parent", "--", "codex"]


def test_both_routes_append_and_send() -> None:
    kind = AgentKind(
        name="both",
        start=("x",),
        resume=None,
        session_id=default_kinds.get("codex").session_id,
        interrupt_keys=(),
        turn_end=default_kinds.get("codex").turn_end,
        usage_source=default_kinds.get("codex").usage_source,
        launch=None,
        hooks=None,
        usage_command=None,
        source="test",
        rules_injection=RulesInjection.BOTH,
    )
    assert appends(kind) and sends(kind)
