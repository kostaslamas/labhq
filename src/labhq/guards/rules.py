"""What counts as publishing: the git and gh commands a worker may not run.

Workers commit inside their worktree; the engine publishes after an approval (plan §5,
rule 5). The rules are data: a git subcommand maps to a handler, and gh is denied unless the
command is listed as read-only.
"""

import re
from collections.abc import Callable, Iterator, Sequence

from labhq.guards.commands import Deny, Handler, Nested, Options, Step, Wrapped, is_dynamic

type GitRule = Callable[[Sequence[str]], Iterator[Step]]


def _always(reason: str) -> GitRule:
    def rule(args: Sequence[str]) -> Iterator[Step]:
        yield Deny(reason)

    return rule


def _matching(reason: str, *patterns: str) -> GitRule:
    compiled = tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)

    def rule(args: Sequence[str]) -> Iterator[Step]:
        if any(regex.search(word) for word in args for regex in compiled):
            yield Deny(reason)

    return rule


# Configuration that redirects or restores pushing, or lets a name stand for a command.
_PUBLISHING_CONFIG = (r"pushurl", r"insteadof", r"^alias\.")
_CONFIG_REWRITES = (
    r"^(--edit|-e|edit|--remove-section|remove-section|--rename-section|rename-section)$",
)


def _remote(args: Sequence[str]) -> Iterator[Step]:
    if args[:1] == ["set-url"] and "--push" in args:
        yield Deny("git remote set-url --push changes where the worktree publishes")


def _rebase(args: Sequence[str]) -> Iterator[Step]:
    for index, word in enumerate(args):
        if word in ("-x", "--exec") and index + 1 < len(args):
            yield Nested(args[index + 1])
        elif word.startswith("--exec="):
            yield Nested(word.removeprefix("--exec="))


def _submodule(args: Sequence[str]) -> Iterator[Step]:
    if "foreach" in args:
        rest = [word for word in args[args.index("foreach") + 1 :] if not word.startswith("-")]
        yield Nested(" ".join(rest))


def _bisect(args: Sequence[str]) -> Iterator[Step]:
    if args[:1] == ["run"]:
        yield Wrapped(tuple(args[1:]))


GIT_SUBCOMMANDS: dict[str, GitRule] = {
    "push": _always("git push publishes commits"),
    "send-pack": _always("git send-pack publishes commits"),
    "http-push": _always("git http-push publishes commits"),
    "config": _matching(
        "git config may not touch push URLs, URL rewrites or aliases",
        *_PUBLISHING_CONFIG,
        *_CONFIG_REWRITES,
    ),
    "remote": _remote,
    "rebase": _rebase,
    "submodule": _submodule,
    "bisect": _bisect,
}

_GIT_OPTIONS = Options(
    takes_value=frozenset(
        {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}
    )
)
_GIT_CONFIG_OPTIONS = frozenset({"-c", "--config-env"})
_PUBLISHING_CONFIG_REGEX = re.compile("|".join(_PUBLISHING_CONFIG), re.IGNORECASE)


def git(args: Sequence[str], open_ended: bool) -> Iterator[Step]:
    configs, rest = _git_global_options(args)
    if any(_PUBLISHING_CONFIG_REGEX.search(entry) for entry in configs):
        yield Deny("git -c may not set push URLs, URL rewrites or aliases")
    if not rest:
        if open_ended:
            yield Deny("git subcommand arrives at run time")
        return
    subcommand, sub_args = rest[0], rest[1:]
    if is_dynamic(subcommand):
        yield Deny(f"git subcommand {subcommand!r} is computed at run time")
        return
    rule = GIT_SUBCOMMANDS.get(subcommand)
    if rule is None:
        return
    if open_ended:
        yield Deny(f"git {subcommand} with arguments that arrive at run time")
    yield from rule(sub_args)


def _git_global_options(args: Sequence[str]) -> tuple[list[str], list[str]]:
    """Return (configuration entries from `-c`/`--config-env`, words from the subcommand on)."""
    configs: list[str] = []
    index = 0
    while index < len(args) and args[index].startswith("-"):
        word = args[index]
        name, has_inline, inline = word.partition("=")
        if has_inline and name in _GIT_OPTIONS.takes_value:
            value = inline
        elif word in _GIT_OPTIONS.takes_value:
            index += 1
            value = args[index] if index < len(args) else ""
            name = word
        else:
            value = ""
        if name in _GIT_CONFIG_OPTIONS:
            configs.append(value)
        index += 1
    return configs, list(args[index:])


# None means every subcommand of the group is read-only.
GH_READ_ONLY: dict[str, frozenset[str] | None] = {
    "pr": frozenset({"view", "list", "status", "diff", "checks"}),
    "issue": frozenset({"view", "list", "status"}),
    "repo": frozenset({"view", "list"}),
    "run": frozenset({"view", "list", "watch"}),
    "workflow": frozenset({"view", "list"}),
    "release": frozenset({"view", "list"}),
    "label": frozenset({"list"}),
    "gist": frozenset({"view", "list"}),
    "auth": frozenset({"status"}),
    "search": None,
    "status": None,
    "help": None,
    "version": None,
}
_GH_VALUE_OPTIONS = frozenset({"-R", "--repo"})
# Prefixes, so `-fkey=value` and `--field=key=value` count too.
_GH_API_FIELDS = ("-f", "-F", "--field", "--raw-field", "--input")
_GH_API_METHOD = ("-X", "--method")


def gh(args: Sequence[str], open_ended: bool) -> Iterator[Step]:
    if open_ended:
        yield Deny("gh with arguments that arrive at run time")
        return
    words = _gh_positionals(args)
    if not words:
        return
    group = words[0]
    if group == "api":
        yield from _gh_api(args)
        return
    if is_dynamic(group) or group not in GH_READ_ONLY:
        yield Deny(f"gh {group} is not a read-only command")
        return
    allowed = GH_READ_ONLY[group]
    if allowed is not None and not allowed.intersection(words[1:2]):
        yield Deny(f"{' '.join(['gh', *words[:2]])} is not a read-only command")


def _gh_positionals(args: Sequence[str]) -> list[str]:
    words: list[str] = []
    skip = False
    for word in args:
        if skip:
            skip = False
        elif word in _GH_VALUE_OPTIONS:
            skip = True
        elif not word.startswith("-"):
            words.append(word)
    return words


def _gh_api(args: Sequence[str]) -> Iterator[Step]:
    """`gh api` is a read only as a GET; fields alone make it a POST, GraphQL included."""
    has_fields = any(word.startswith(_GH_API_FIELDS) for word in args)
    method = "POST" if has_fields else "GET"
    for index, word in enumerate(args):
        if word in _GH_API_METHOD:
            method = args[index + 1] if index + 1 < len(args) else ""
        elif word.startswith(_GH_API_METHOD):
            method = word.removeprefix("--method=").removeprefix("-X")
    if method.upper() != "GET":
        yield Deny(f"gh api with method {method or 'unknown'} writes to the forge")


PROGRAMS: dict[str, Handler] = {"git": git, "gh": gh}
# `git-push` and friends live in git's exec path and run without the `git` front end.
DASH_FORMS: dict[str, str] = {"git-": "git"}
