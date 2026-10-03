"""Check that a release tag agrees with the files it ships (CONTRIBUTING.md §5).

Given `v0.5.0-beta.1`, the tag must be annotated, `pyproject.toml` must hold the matching
PEP 440 version `0.5.0b1`, `CHANGELOG.md` must have the tag's section, and the root files
of an open-source release (`LICENSE`, `SECURITY.md`, `CHANGELOG.md`) must exist.
"""

import argparse
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

ROOT_FILES = ("LICENSE", "SECURITY.md", "CHANGELOG.md")

# SemVer pre-release label in the tag -> PEP 440 pre-release segment in pyproject.toml.
PRE_RELEASE_SEGMENTS = {"alpha": "a", "beta": "b", "rc": "rc"}

TAG_PATTERN = re.compile(
    r"^v(?P<release>\d+\.\d+\.\d+)"
    rf"(?:-(?P<label>{'|'.join(PRE_RELEASE_SEGMENTS)})\.(?P<number>\d+))?$"
)


class ReleaseError(Exception):
    pass


def pep440_version(tag: str) -> str:
    match = TAG_PATTERN.match(tag)
    if match is None:
        labels = ", ".join(PRE_RELEASE_SEGMENTS)
        raise ReleaseError(
            f"tag {tag!r} is not vX.Y.Z or vX.Y.Z-<label>.N with a label in: {labels}"
        )
    version = match["release"]
    if match["label"] is not None:
        version += f"{PRE_RELEASE_SEGMENTS[match['label']]}{match['number']}"
    return version


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=False
    )


def check_root_files(repo: Path, tag: str) -> None:
    missing = [name for name in ROOT_FILES if not (repo / name).is_file()]
    if missing:
        raise ReleaseError(f"missing at the repository root: {', '.join(missing)}")


def check_version(repo: Path, tag: str) -> None:
    expected = pep440_version(tag)
    with (repo / "pyproject.toml").open("rb") as handle:
        actual = tomllib.load(handle)["project"]["version"]
    if actual != expected:
        raise ReleaseError(f"pyproject.toml has version {actual!r}, tag {tag} needs {expected!r}")


def check_annotated(repo: Path, tag: str) -> None:
    result = _git(repo, "cat-file", "-t", f"refs/tags/{tag}")
    if result.returncode != 0:
        raise ReleaseError(f"tag {tag} does not exist")
    if result.stdout.strip() != "tag":
        raise ReleaseError(f"tag {tag} is lightweight; release tags are annotated")


def check_changelog(repo: Path, tag: str) -> None:
    path = repo / "CHANGELOG.md"
    if not path.is_file():
        raise ReleaseError("CHANGELOG.md is missing")
    heading = re.compile(rf"^## {re.escape(tag)}(?:\s|$)", re.MULTILINE)
    if heading.search(path.read_text(encoding="utf-8")) is None:
        raise ReleaseError(
            f"CHANGELOG.md has no section for {tag}: run "
            f"`uv run python -m tools.changelog --tag {tag}` before tagging"
        )


CHECKS: tuple[Callable[[Path, str], None], ...] = (
    check_root_files,
    check_version,
    check_annotated,
    check_changelog,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="the release tag, for example v0.5.0-beta.1")
    parser.add_argument("--repo", type=Path, default=Path())
    args = parser.parse_args(argv)

    errors: list[str] = []
    for check in CHECKS:
        try:
            check(args.repo, args.tag)
        except ReleaseError as error:
            errors.append(str(error))
    for error in errors:
        print(f"error: {error}")
    if errors:
        return 1
    print(f"release_check: {args.tag} is ready to publish as {pep440_version(args.tag)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
