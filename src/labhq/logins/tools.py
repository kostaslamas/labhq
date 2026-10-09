"""`tool -> how to check its login and how to start it`, one registration each.

labhq asks a tool whether it is logged in through the tool's own documented status command,
or from the login dialog on its screen, and starts the tool's own login command when it is
not. It never reads a credential file or token (ADR 0001): the tool stores its credentials,
labhq sees a link, and the owner finishes in a browser.

The commands are what each tool's documentation lists; they are re-checked by hand in
docs/checks/login-links.md, because a tool can rename a subcommand between releases.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit

from labhq.adapters.tmux.agents import default_kinds
from labhq.approvals.registry import Registry

# `capture-pane -J` joins wrapped lines, so a long link arrives whole.
URL_PATTERN = re.compile(r"https://[^\s<>\"'`)\]]+")


@dataclass(frozen=True)
class LoginTool:
    name: str
    display_name: str
    # The tool's own status command, or None when it has none and the screen decides.
    status: tuple[str, ...] | None
    # The tool's own login command, or None when it has no login flow of its own.
    login: tuple[str, ...] | None
    # Seconds a login attempt stays valid: the tool's own timeout, with a margin.
    timeout_seconds: int
    # Status output that means "not logged in" although the command exits 0.
    logged_out_pattern: str | None = None
    # A JSON status document whose boolean field says whether the tool is logged in.
    status_json_key: str | None = None
    # The login dialog as the tool's screen shows it, and the reason a run fails with.
    screen_pattern: str | None = None
    screen_reason: str | None = None
    # Hosts the login link may point at; empty means the tool lets the owner pick a provider.
    hosts: tuple[str, ...] = ()
    # The tool then waits for a code to be pasted back into the terminal.
    code_pattern: str | None = r"(?i)paste.{0,40}code|enter.{0,20}(authorization )?code"
    source: str = ""

    def accepts(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme != "https" or parts.username or parts.password or not host:
            return False
        return not self.hosts or any(host == h or host.endswith(f".{h}") for h in self.hosts)

    def find_url(self, screen: str) -> str | None:
        """The last acceptable link on the screen: the newest one is the live attempt."""
        links = [m.rstrip(".,;") for m in URL_PATTERN.findall(screen)]
        return next((link for link in reversed(links) if self.accepts(link)), None)

    def asks_for_code(self, screen: str) -> bool:
        return self.code_pattern is not None and re.search(self.code_pattern, screen) is not None


def _kind_screen(kind: str) -> tuple[str | None, str | None]:
    """The login dialog an agent kind already knows (`blocking_screens`), as data."""
    screens = default_kinds.get(kind).blocking_screens
    found = next((s for s in screens if s.name == "login"), None)
    return (found.pattern, found.reason) if found else (None, None)


def _with_kind_screen(tool: LoginTool, kind: str) -> LoginTool:
    pattern, reason = _kind_screen(kind)
    return LoginTool(**{**tool.__dict__, "screen_pattern": pattern, "screen_reason": reason})


login_tools: Registry[LoginTool] = Registry("login tool")

for _tool, _kind in (
    (
        LoginTool(
            "claude-code",
            "Claude Code",
            status=("claude", "auth", "status", "--json"),
            status_json_key="loggedIn",
            login=("claude", "auth", "login"),
            timeout_seconds=600,
            hosts=("claude.ai", "claude.com", "anthropic.com"),
            source="https://code.claude.com/docs/en/cli-reference (claude auth login, auth status)",
        ),
        "claude-code",
    ),
    (
        LoginTool(
            "codex",
            "Codex",
            status=("codex", "login", "status"),
            logged_out_pattern=r"(?i)not logged in",
            login=("codex", "login"),
            timeout_seconds=900,
            hosts=("openai.com", "chatgpt.com"),
            source="openai/codex codex-rs/cli/src/login.rs (login, login status)",
        ),
        "codex",
    ),
    (
        LoginTool(
            "gemini",
            "Gemini CLI",
            # No status subcommand: the login dialog on its screen is the check.
            status=None,
            login=("gemini",),
            timeout_seconds=600,
            hosts=("google.com",),
            source="google-gemini/gemini-cli docs/get-started/authentication.md",
        ),
        "gemini",
    ),
):
    login_tools.register(_tool.name, _with_kind_screen(_tool, _kind))
login_tools.register(
    "aider",
    LoginTool(
        "aider",
        "Aider",
        # Aider talks to a provider with an API key and has no login of its own.
        status=None,
        login=None,
        timeout_seconds=600,
        source="Aider-AI/aider website/docs/config/api-keys.md",
    ),
)
login_tools.register(
    "opencode",
    LoginTool(
        "opencode",
        "OpenCode",
        status=("opencode", "auth", "list"),
        logged_out_pattern=r"(?i)\b0 credentials\b|no credentials",
        login=("opencode", "auth", "login"),
        timeout_seconds=600,
        source="sst/opencode packages/opencode/src/cli/cmd/auth.ts (auth login, auth list)",
    ),
)
login_tools.register(
    "cursor",
    LoginTool(
        "cursor",
        "Cursor CLI",
        status=("cursor-agent", "status"),
        logged_out_pattern=r"(?i)not logged in",
        login=("cursor-agent", "login"),
        timeout_seconds=600,
        hosts=("cursor.com", "cursor.sh"),
        source="https://cursor.com/docs/cli/reference/authentication (login, status)",
    ),
)


def login_tool_names() -> Iterator[str]:
    return iter(login_tools)
