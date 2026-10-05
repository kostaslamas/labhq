"""The environment of an agent adopted outside a worktree: push deterred, not prevented.

An adopted agent works in the owner's main checkout (ADR 0005), where labhq writes no
config: the repository's own config stays byte-for-byte as the owner left it. Instead,
`GIT_CONFIG_COUNT` entries in the agent's environment point every remote's push URL at the
disabled URL and add an empty `pushInsteadOf` prefix for any other URL, on top of
`worker_environment`.

This is a deterrent, not a guarantee. The agent runs as the owner: `env -u GIT_CONFIG_COUNT
git push` drops the entries, and an SSH key file without a passphrase needs no agent socket.
Only a sandbox or a separate OS user prevents a push (plan §5, rule 6).
"""

from collections.abc import Iterable, Mapping
from pathlib import Path

from labhq.worktrees.environment import worker_environment
from labhq.worktrees.git import GitError, run_git
from labhq.worktrees.manager import PUSH_DISABLED_URL


def push_deterrent_config(remotes: Iterable[str]) -> list[tuple[str, str]]:
    entries = [(f"remote.{remote}.pushurl", PUSH_DISABLED_URL) for remote in remotes]
    # An empty prefix matches every URL, so a remote added later or a URL typed on the
    # command line is rewritten too. Remotes with a push URL ignore it, hence the entries.
    entries.append((f"url.{PUSH_DISABLED_URL}.pushInsteadOf", ""))
    return entries


def remotes_of(repo: Path) -> list[str]:
    try:
        return run_git("remote", cwd=repo).split()
    except GitError as error:
        if "not a git repository" not in error.stderr:
            raise
        return []


def adopted_environment(repo: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """`worker_environment(base)` with pushes from `repo`'s remotes pointed nowhere."""
    environment = worker_environment(base)
    start = int(environment["GIT_CONFIG_COUNT"])
    extra = push_deterrent_config(remotes_of(repo))
    for offset, (key, value) in enumerate(extra):
        environment[f"GIT_CONFIG_KEY_{start + offset}"] = key
        environment[f"GIT_CONFIG_VALUE_{start + offset}"] = value
    environment["GIT_CONFIG_COUNT"] = str(start + len(extra))
    return environment
