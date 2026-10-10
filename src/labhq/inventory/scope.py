"""Which folders the scan may look in: the roots the owner set, minus the exclusions.

A session belongs to the inventory only if its working directory is inside a root and not
inside an excluded folder. Membership is decided on the real path, so `..` and symlinks
cannot lead out of a root. With no roots the scan is machine-wide.
"""

import fnmatch
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

GLOB_CHARS = re.compile(r"[*?\[]")
NOT_ALNUM = re.compile(r"[^A-Za-z0-9]")


def real(path: Path | str) -> Path:
    return Path(os.path.realpath(Path(path).expanduser()))


@dataclass(frozen=True)
class Scope:
    roots: tuple[Path, ...] = ()
    # Folders or glob patterns, already expanded with `~`.
    exclude: tuple[str, ...] = ()

    @property
    def machine_wide(self) -> bool:
        return not self.roots

    def contains(self, folder: Path) -> bool:
        if self.machine_wide:
            return True
        target = real(folder)
        if not any(target.is_relative_to(root) for root in self.roots):
            return False
        return not self.excluded(target)

    def excluded(self, folder: Path) -> bool:
        """Whether an exclusion covers this folder (compared on its real path)."""
        target = real(folder)
        return any(_excluded(target, pattern) for pattern in self.exclude)

    def may_hold(self, encoded: str) -> bool:
        """Whether a folder name that encodes a path (Claude Code's) can lie in a root.

        The encoding is lossy, so this only rules folders out: a yes still needs `contains`.
        """
        if self.machine_wide:
            return True
        name = NOT_ALNUM.sub("-", encoded)
        return any(name.startswith(NOT_ALNUM.sub("-", str(root))) for root in self.roots)


def _excluded(target: Path, pattern: str) -> bool:
    if GLOB_CHARS.search(pattern):
        # A pattern that matches a folder excludes everything below it.
        return any(fnmatch.fnmatchcase(str(p), pattern) for p in (target, *target.parents))
    return target.is_relative_to(real(pattern))


def build_scope(roots: Iterable[str | Path], exclude: Iterable[str]) -> Scope:
    resolved = dict.fromkeys(real(root) for root in roots)
    patterns = tuple(str(Path(item).expanduser()) for item in exclude)
    return Scope(tuple(resolved), patterns)


@dataclass
class ScopeFilter:
    """One scan's view of the scope: it counts what it turned away, never what it was."""

    scope: Scope = field(default_factory=Scope)
    left_out: int = 0

    def allows(self, folder: Path) -> bool:
        if self.scope.contains(folder):
            return True
        self.left_out += 1
        return False

    def dir_may_hold(self, encoded: str) -> bool:
        return self.scope.may_hold(encoded)

    def skip(self, count: int = 1) -> None:
        self.left_out += count
