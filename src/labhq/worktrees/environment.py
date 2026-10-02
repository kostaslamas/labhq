"""The environment a worker process starts with: no way to authenticate a push.

The list of dropped variables is the policy. A new credential source is a new entry here.
`ANTHROPIC_API_KEY` passes through untouched (ADR 0001).
"""

import os
from collections.abc import Mapping

DROPPED_VARIABLES: frozenset[str] = frozenset(
    {
        # Forge tokens that gh, hub, glab and CI tooling read before any config file.
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
        "GITLAB_TOKEN",
        "GL_TOKEN",
        "CI_JOB_TOKEN",
        "GITEA_TOKEN",
        "BITBUCKET_TOKEN",
        # SSH agent access and password prompts.
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "SSH_ASKPASS",
        "SSH_ASKPASS_REQUIRE",
        "GIT_ASKPASS",
        # Transport commands that could bring their own credentials.
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        # Injected configuration, which could restore a credential helper or a push URL.
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_COUNT",
    }
)
DROPPED_PREFIXES: tuple[str, ...] = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")

FIXED_VARIABLES: Mapping[str, str] = {
    # Fail instead of asking for a username or password nobody will type.
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
}
# Applied through GIT_CONFIG_COUNT, which outranks every config file. An empty helper
# resets the list, so helpers from the user's global or system config never run.
WORKER_GIT_CONFIG: tuple[tuple[str, str], ...] = (("credential.helper", ""),)


def is_dropped(name: str) -> bool:
    return name in DROPPED_VARIABLES or name.startswith(DROPPED_PREFIXES)


def worker_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return `base` (default: this process's environment) stripped of git credentials."""
    source = os.environ if base is None else base
    environment = {name: value for name, value in source.items() if not is_dropped(name)}
    environment.update(FIXED_VARIABLES)
    environment["GIT_CONFIG_COUNT"] = str(len(WORKER_GIT_CONFIG))
    for index, (key, value) in enumerate(WORKER_GIT_CONFIG):
        environment[f"GIT_CONFIG_KEY_{index}"] = key
        environment[f"GIT_CONFIG_VALUE_{index}"] = value
    return environment
