"""Fail when application code refers to Claude credential files or token variables.

ADR 0001: labhq never reads, stores or forwards Claude credentials. It starts the
unmodified Claude Code binary, which uses the login the user already completed. The
only credential variable labhq may name is ``ANTHROPIC_API_KEY``, which it passes
through to the child process when the user set it.

Standard library only, so it runs before the project's environment exists.

Usage: python tools/guards/credential_refs.py [ROOT ...]   (default: src migrations)
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOTS = ("src", "migrations")

EXIT_CLEAN = 0
EXIT_FOUND = 1
EXIT_UNUSABLE = 2

SKIPPED_DIRS = frozenset({"__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"})


@dataclass(frozen=True)
class Pattern:
    name: str
    regex: re.Pattern[str]
    reason: str


def pattern(name: str, regex: str, reason: str) -> Pattern:
    # Case-insensitive: pydantic-settings maps a lower-case field to the same variable.
    return Pattern(name=name, regex=re.compile(regex, re.IGNORECASE), reason=reason)


# A new forbidden reference is a new row here, never a new branch in the scanner.
PATTERNS: tuple[Pattern, ...] = (
    pattern(
        "credentials-file",
        r"\.credentials\.json",
        "Claude Code stores its login in this file",
    ),
    pattern(
        "keychain-entry",
        r"Claude Code-credentials",
        "macOS keychain item that holds the Claude Code login",
    ),
    pattern(
        "claude-token-variable",
        r"\bCLAUDE_\w*TOKEN\b",
        "Claude token variables such as CLAUDE_CODE_OAUTH_TOKEN",
    ),
    pattern(
        "anthropic-credential-variable",
        r"\bANTHROPIC_(?!API_KEY\b)\w*(?:TOKEN|KEY|SECRET)\b",
        "Anthropic credential variables other than ANTHROPIC_API_KEY",
    ),
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    match: str
    pattern: Pattern

    def render(self) -> str:
        where = f"{self.path}:{self.line}"
        return f"{where}: {self.match!r} ({self.pattern.name}: {self.pattern.reason})"


def files_under(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not SKIPPED_DIRS.intersection(path.parts):
            yield path


def scan_file(path: Path, patterns: tuple[Pattern, ...]) -> Iterator[Finding]:
    text = path.read_bytes().decode("utf-8", errors="replace")
    for line_number, line in enumerate(text.splitlines(), start=1):
        for entry in patterns:
            for match in entry.regex.finditer(line):
                yield Finding(path=path, line=line_number, match=match.group(), pattern=entry)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when code refers to Claude credential files or tokens."
    )
    parser.add_argument("roots", nargs="*", type=Path, default=[Path(r) for r in DEFAULT_ROOTS])
    args = parser.parse_args(argv)

    roots: list[Path] = args.roots
    missing = [root for root in roots if not root.is_dir()]
    if missing:
        names = ", ".join(str(root) for root in missing)
        print(
            f"error: not a directory: {names}. Nothing would be checked there.",
            file=sys.stderr,
        )
        return EXIT_UNUSABLE

    files = [path for root in roots for path in files_under(root)]
    if not files:
        print(f"error: no files under {', '.join(map(str, roots))}.", file=sys.stderr)
        return EXIT_UNUSABLE

    findings = [finding for path in files for finding in scan_file(path, PATTERNS)]
    for finding in findings:
        print(finding.render())

    print(f"Checked {len(files)} files under {', '.join(map(str, roots))}.")
    if findings:
        print(
            f"error: {len(findings)} references to Claude credentials found. ADR 0001 "
            "allows only ANTHROPIC_API_KEY, passed through to the child process.",
            file=sys.stderr,
        )
        return EXIT_FOUND
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
