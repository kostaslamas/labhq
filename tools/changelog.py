"""Generate CHANGELOG.md from the git history with git-cliff (CONTRIBUTING.md §5).

`uv run python -m tools.changelog` rewrites the file from the tags that exist.
`--check` regenerates it in memory and fails on any difference, which is how CI catches a
hand edit. `--tag v0.5.0-beta.1` titles the unreleased commits with the tag about to be
created, so the release commit can carry its own section before the tag exists.
"""

import argparse
import difflib
import shutil
import subprocess
import sys
from pathlib import Path

CHANGELOG = "CHANGELOG.md"
CONFIG = "cliff.toml"


def git_cliff() -> str:
    # The dev dependency installs the binary next to the interpreter; PATH is the fallback
    # for a run outside the project environment.
    beside = Path(sys.executable).parent / "git-cliff"
    if beside.is_file():
        return str(beside)
    found = shutil.which("git-cliff")
    if found is None:
        raise SystemExit("git-cliff not found: run `uv sync` to install the dev dependencies")
    return found


def render(repo: Path, tag: str | None = None) -> str:
    command = [git_cliff(), "--config", str(repo / CONFIG), "--repository", str(repo)]
    if tag is not None:
        command += ["--tag", tag]
    result = subprocess.run(
        command, cwd=repo, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git-cliff failed:\n{result.stderr}")
    return result.stdout


def check(repo: Path) -> int:
    path = repo / CHANGELOG
    expected = render(repo)
    actual = path.read_text(encoding="utf-8") if path.is_file() else ""
    if actual == expected:
        print(f"changelog: {CHANGELOG} matches the history")
        return 0
    diff = difflib.unified_diff(
        actual.splitlines(keepends=True),
        expected.splitlines(keepends=True),
        fromfile=f"{CHANGELOG} (checked in)",
        tofile=f"{CHANGELOG} (generated)",
    )
    sys.stdout.writelines(diff)
    print(
        f"\nerror: {CHANGELOG} differs from the history. It is generated, never edited by "
        "hand: run `uv run python -m tools.changelog` and commit the result."
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path())
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail if the file is out of date")
    mode.add_argument("--tag", help="title unreleased commits with this upcoming tag")
    args = parser.parse_args(argv)

    repo: Path = args.repo.resolve()
    if args.check:
        return check(repo)
    (repo / CHANGELOG).write_text(render(repo, args.tag), encoding="utf-8")
    print(f"changelog: wrote {CHANGELOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
