"""The private-terms guard fails on any occurrence and never reveals the term."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "guards" / "private_terms.py"

# Synthetic terms. The second has mixed case and a non-ASCII letter, for case folding.
TERMS = "zebrafjord-alpha\n\nKestrelÖmega\n"
FIRST_TERM_NUMBER = 1
SECOND_TERM_NUMBER = 3


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet", "--initial-branch=main")
    git(tmp_path, "config", "user.name", "Guard Test")
    git(tmp_path, "config", "user.email", "guard@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    commit(tmp_path, "README.md", "clean content\n", "docs: add readme")
    return tmp_path


def commit(repo: Path, name: str, content: str, message: str) -> str:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "--quiet", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def run_guard(
    repo: Path, *args: str, terms: str | None = TERMS
) -> subprocess.CompletedProcess[str]:
    env = {
        key: value for key, value in os.environ.items() if key != "LABHQ_PRIVATE_TERMS"
    }
    if terms is not None:
        env["LABHQ_PRIVATE_TERMS"] = terms
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def assert_no_term_leaks(result: subprocess.CompletedProcess[str]) -> None:
    output = (result.stdout + result.stderr).casefold()
    for term in filter(None, TERMS.splitlines()):
        folded = term.casefold()
        # No fragment of the term either: every substring of length 4 is checked.
        for start in range(len(folded) - 3):
            assert folded[start : start + 4] not in output


def test_clean_repository_passes(repo: Path) -> None:
    result = run_guard(repo, "--commits", "HEAD")

    assert result.returncode == 0, result.stderr
    assert "Checked 1 tracked files and 1 commit messages in HEAD." in result.stdout


def test_term_in_tracked_file_fails_without_printing_the_term(repo: Path) -> None:
    commit(
        repo,
        "notes/today.md",
        "line one\nmet ZEBRAFJORD-ALPHA here\n",
        "docs: add notes",
    )

    result = run_guard(repo)

    assert result.returncode == 1
    assert f"notes/today.md:2: private term #{FIRST_TERM_NUMBER}" in result.stdout
    assert_no_term_leaks(result)


def test_term_matches_case_insensitively_beyond_ascii(repo: Path) -> None:
    commit(repo, "data.txt", "kestrelömega\n", "chore: add data")

    result = run_guard(repo)

    assert result.returncode == 1
    assert f"data.txt:1: private term #{SECOND_TERM_NUMBER}" in result.stdout
    assert_no_term_leaks(result)


def test_term_in_path_withholds_the_path(repo: Path) -> None:
    commit(repo, "zebrafjord-alpha/plan.md", "clean\n", "docs: add plan")

    result = run_guard(repo)

    assert result.returncode == 1
    assert "path withheld" in result.stdout
    assert_no_term_leaks(result)


def test_term_in_commit_message_fails(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    sha = commit(repo, "src.py", "x = 1\n", "feat: add x\n\nAsked by kestrelÖMEGA")

    result = run_guard(repo, "--commits", f"{base}..HEAD")

    assert result.returncode == 1
    assert (
        f"commit {sha} message:3: private term #{SECOND_TERM_NUMBER}" in result.stdout
    )
    assert_no_term_leaks(result)


def test_commit_outside_the_range_is_not_scanned(repo: Path) -> None:
    commit(repo, "src.py", "x = 1\n", "feat: add x for zebrafjord-alpha")
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, "src2.py", "y = 2\n", "feat: add y")

    result = run_guard(repo, "--commits", f"{base}..HEAD")

    assert result.returncode == 0, result.stdout
    assert "1 commit messages" in result.stdout


@pytest.mark.parametrize(
    "terms", [None, "", "\n  \n"], ids=["missing", "empty", "blank"]
)
def test_missing_or_empty_terms_fail_with_a_clear_message(
    repo: Path, terms: str | None
) -> None:
    result = run_guard(repo, terms=terms)

    assert result.returncode == 2
    assert "LABHQ_PRIVATE_TERMS is missing or empty" in result.stderr
    assert "forks" in result.stderr


def test_invalid_range_fails(repo: Path) -> None:
    result = run_guard(repo, "--commits", "no-such-ref..HEAD")

    assert result.returncode == 2
    assert "git failed" in result.stderr


def test_outside_a_repository_fails(tmp_path: Path) -> None:
    result = run_guard(tmp_path)

    assert result.returncode == 2
