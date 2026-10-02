"""The environment a Claude Code child process sees (ADR 0001).

The SDK starts the child with the parent's whole environment and lays `options.env` over
it; it offers no way to drop a variable. So the adapter blanks every inherited variable
outside a small allowlist, and passes `ANTHROPIC_API_KEY` only when the user set it. The
binary's own login lives in its own files, which labhq never reads.
"""

from collections.abc import Mapping

API_KEY_VARIABLE = "ANTHROPIC_API_KEY"

# What a process needs to find its tools, home, locale, temp space and network proxy.
INHERITED_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LANGUAGE",
        "TERM",
        "TZ",
        "TMPDIR",
        "TEMP",
        "TMP",
        "PWD",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
        # Windows equivalents of the above.
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
        "WINDIR",
        "APPDATA",
        "LOCALAPPDATA",
        "USERPROFILE",
    }
)
INHERITED_PREFIXES = ("LC_", "XDG_")
# Variables the SDK sets for its own protocol with the child. Blanking an inherited copy
# would stop the SDK from choosing its value, so they are left alone.
SDK_PROTOCOL_NAMES = frozenset({"CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SDK_READS_SESSION_STATE"})


def is_inherited(name: str) -> bool:
    return (
        name in INHERITED_NAMES or name in SDK_PROTOCOL_NAMES or name.startswith(INHERITED_PREFIXES)
    )


def child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The `options.env` overlay for a run, given the parent's environment."""
    overlay = {name: "" for name in environ if not is_inherited(name)}
    api_key = environ.get(API_KEY_VARIABLE)
    if api_key:
        overlay[API_KEY_VARIABLE] = api_key
    else:
        overlay.pop(API_KEY_VARIABLE, None)
    return overlay
