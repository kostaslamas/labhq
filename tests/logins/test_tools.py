"""The login check per tool, against fakes: status commands and login dialogs."""

import pytest

from labhq.logins import LoginState, check_login, login_tools
from tests.logins.conftest import FakeStatus

TOOLS = ["claude-code", "codex", "gemini", "aider", "opencode", "cursor"]


def test_every_supported_tool_is_registered() -> None:
    assert sorted(login_tools) == sorted(TOOLS)


@pytest.mark.parametrize(
    ("tool", "out", "logged_in"),
    [
        ("claude-code", (0, '{"loggedIn": true, "extra": "ignored"}'), True),
        ("claude-code", (0, '{"loggedIn": false}'), False),
        ("claude-code", (0, "not json"), False),
        ("codex", (0, "Logged in using ChatGPT"), True),
        ("codex", (1, "Not logged in"), False),
        ("codex", (0, "Not logged in"), False),
        ("opencode", (0, "0 credentials"), False),
        ("opencode", (0, "OpenAI oauth\n1 credentials"), True),
        ("cursor", (0, "Not logged in"), False),
        ("cursor", (0, "Logged in as someone"), True),
    ],
)
def test_the_status_command_decides(
    status: FakeStatus, tool: str, out: tuple[int, str], logged_in: bool
) -> None:
    definition = login_tools.get(tool)
    assert definition.status is not None
    status.answers[definition.status] = out

    expected = LoginState.LOGGED_IN if logged_in else LoginState.LOGGED_OUT
    assert check_login(definition, runner=status) is expected


def test_a_missing_binary_is_unknown_not_logged_out(status: FakeStatus) -> None:
    assert check_login(login_tools.get("codex"), runner=status) is LoginState.UNKNOWN


def test_a_tool_without_a_status_command_is_judged_by_its_dialog() -> None:
    gemini = login_tools.get("gemini")
    assert gemini.status is None

    shown = check_login(gemini, screen="How would you like to authenticate for this project?")
    clear = check_login(gemini, screen="> Ask Gemini anything")

    assert (shown, clear) == (LoginState.LOGGED_OUT, LoginState.LOGGED_IN)
    assert check_login(gemini) is LoginState.UNKNOWN


@pytest.mark.parametrize("tool", ["claude-code", "codex", "gemini"])
def test_the_dialog_is_the_one_the_tmux_agent_kind_already_blocks_on(tool: str) -> None:
    from labhq.adapters.tmux.agents import default_kinds

    definition = login_tools.get(tool)
    login = next(s for s in default_kinds.get(tool).blocking_screens if s.name == "login")

    assert (definition.screen_pattern, definition.screen_reason) == (login.pattern, login.reason)


def test_only_an_https_link_to_the_tools_own_host_is_taken() -> None:
    codex = login_tools.get("codex")
    screen = (
        "docs: http://auth.openai.com/plain\n"
        "docs: https://example.org/phish\n"
        "open https://user:pw@auth.openai.com/x\n"
        "open https://auth.openai.com/oauth/authorize?state=1.\n"
    )

    assert codex.find_url(screen) == "https://auth.openai.com/oauth/authorize?state=1"


def test_no_acceptable_link_is_none() -> None:
    assert login_tools.get("codex").find_url("nothing to see") is None
