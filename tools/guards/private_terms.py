"""Fail when a private term appears in a tracked file, path or commit message.

The terms come from the ``LABHQ_PRIVATE_TERMS`` environment variable, one per line,
which CI fills from the repository secret of the same name. CI logs are public and
GitHub does not reliably mask multi-line secrets, so this script never prints a term
or any text around a match: a finding names the location and the term's line number
in the variable. A path that itself contains a term is withheld as well.

Standard library only, so it runs before the project's environment exists.

Usage: python tools/guards/private_terms.py [--commits REV_RANGE]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "LABHQ_PRIVATE_TERMS"

EXIT_CLEAN = 0
EXIT_FOUND = 1
EXIT_UNUSABLE = 2

MISSING_TERMS = (
    f"{ENV_VAR} is missing or empty, so there is nothing to check against. CI "
    "fills it from the repository secret of the same name. Pull requests from "
    "forks receive no secrets, so this guard cannot run on them; push the branch "
    "to this repository instead."
)

# git ends each commit with a NUL (%x00), which a commit message cannot contain.
RECORD_SEPARATOR = "\0"


@dataclass(frozen=True)
class Term:
    # 1-based line of the term in the variable, so the owner can find it in the secret.
    number: int
    folded: str


@dataclass(frozen=True)
class Finding:
    location: str
    term: Term

    def render(self) -> str:
        return f"{self.location}: private term #{self.term.number}"


def parse_terms(raw: str | None) -> list[Term]:
    if not raw:
        return []
    terms = []
    for number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if stripped:
            terms.append(Term(number=number, folded=stripped.casefold()))
    return terms


def terms_in(text: str, terms: list[Term]) -> Iterator[Term]:
    folded = text.casefold()
    return (term for term in terms if term.folded in folded)


def scan_text(location: str, text: str, terms: list[Term]) -> Iterator[Finding]:
    for line_number, line in enumerate(text.splitlines(), start=1):
        for term in terms_in(line, terms):
            yield Finding(location=f"{location}:{line_number}", term=term)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def tracked_paths(repo: Path) -> list[str]:
    return [path for path in git(repo, "ls-files", "-z").split("\0") if path]


def read_tracked(path: Path) -> str | None:
    if path.is_symlink():
        return str(path.readlink())
    if not path.is_file():
        # Deleted in the working tree, or a submodule: there is no content to read.
        return None
    return path.read_bytes().decode("utf-8", errors="replace")


def scan_files(repo: Path, paths: list[str], terms: list[Term]) -> Iterator[Finding]:
    for index, path in enumerate(paths, start=1):
        path_terms = list(terms_in(path, terms))
        shown = f"<tracked file #{index}, path withheld>" if path_terms else path
        for term in path_terms:
            yield Finding(location=f"{shown} (path)", term=term)
        text = read_tracked(repo / path)
        if text is not None:
            yield from scan_text(shown, text, terms)


def commit_messages(repo: Path, rev_range: str) -> list[tuple[str, str]]:
    output = git(repo, "log", "--format=%H%n%B%x00", rev_range, "--")
    commits = []
    for record in output.split(RECORD_SEPARATOR):
        sha, _, message = record.strip("\n").partition("\n")
        if sha:
            commits.append((sha, message))
    return commits


def scan_commits(commits: list[tuple[str, str]], terms: list[Term]) -> Iterator[Finding]:
    for sha, message in commits:
        yield from scan_text(f"commit {sha} message", message, terms)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when a private term appears in the repository."
    )
    parser.add_argument(
        "--commits",
        metavar="REV_RANGE",
        help="scan the messages of the commits in this range, for example base..head",
    )
    args = parser.parse_args(argv)

    terms = parse_terms(os.environ.get(ENV_VAR))
    if not terms:
        print(f"error: {MISSING_TERMS}", file=sys.stderr)
        return EXIT_UNUSABLE

    repo = Path.cwd()
    try:
        paths = tracked_paths(repo)
        commits = commit_messages(repo, args.commits) if args.commits else []
    except subprocess.CalledProcessError as error:
        print(f"error: git failed: {error.stderr.strip()}", file=sys.stderr)
        return EXIT_UNUSABLE
    if not paths:
        print(
            "error: no tracked files found; run this from the repository root.",
            file=sys.stderr,
        )
        return EXIT_UNUSABLE

    findings = [*scan_files(repo, paths, terms), *scan_commits(commits, terms)]
    for finding in findings:
        print(finding.render())

    commit_scope = "no commit messages (no --commits range given)"
    if args.commits:
        commit_scope = f"{len(commits)} commit messages in {args.commits}"
    print(f"Checked {len(paths)} tracked files and {commit_scope}.")
    print(f"Terms checked: {len(terms)}.")
    if findings:
        print(
            f"error: {len(findings)} private term occurrences found. Each finding "
            f"names the term's line in {ENV_VAR}; terms are never printed.",
            file=sys.stderr,
        )
        return EXIT_FOUND
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
