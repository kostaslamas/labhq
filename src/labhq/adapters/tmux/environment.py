"""The environments of the private tmux server and of each session it runs (ADR 0003).

A private server alone does not keep the owner's variables out: the server starts from the
environment of the client that launches it, and `update-environment` copies more from every
client that runs `new-session`. So every tmux command runs with the allowlist of the SDK
adapter (ADR 0001), the server's configuration empties `update-environment`, and each
session gets its variables explicitly: the allowlist with `worker_environment` on top.
"""

from collections.abc import Mapping

from labhq.adapters.claude_env import API_KEY_VARIABLE, is_inherited
from labhq.worktrees import worker_environment


def client_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """What a `tmux` client process sees: the allowlist, and the API key only when set."""
    allowed = {name: value for name, value in environ.items() if is_inherited(name)}
    api_key = environ.get(API_KEY_VARIABLE)
    if api_key:
        allowed[API_KEY_VARIABLE] = api_key
    return allowed


def session_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The variables a session receives through `new-session -e`."""
    return worker_environment(client_environment(environ))
