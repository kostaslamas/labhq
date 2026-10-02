"""The credential-reference guard enforces ADR 0001 on application code."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "guards" / "credential_refs.py"


def run_guard(cwd: Path, *roots: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *roots],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "src" / "labhq").mkdir(parents=True)
    (tmp_path / "migrations").mkdir()
    (tmp_path / "src" / "labhq" / "clean.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (tmp_path / "migrations" / "env.py").write_text(
        "# migration env\n", encoding="utf-8"
    )
    return tmp_path


def plant(tree: Path, relative: str, content: str) -> None:
    path = tree / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_clean_tree_passes(tree: Path) -> None:
    result = run_guard(tree)

    assert result.returncode == 0, result.stdout
    assert "Checked 2 files under src, migrations" in result.stdout


@pytest.mark.parametrize(
    ("line", "pattern_name"),
    [
        ('path = Path.home() / ".claude" / ".credentials.json"', "credentials-file"),
        ('os.environ["CLAUDE_CODE_OAUTH_TOKEN"]', "claude-token-variable"),
        ('env.pop("ANTHROPIC_AUTH_TOKEN")', "anthropic-credential-variable"),
        ("anthropic_auth_token: str = ''", "anthropic-credential-variable"),
        (
            'security find-generic-password -s "Claude Code-credentials"',
            "keychain-entry",
        ),
    ],
)
def test_credential_reference_in_src_fails(
    tree: Path, line: str, pattern_name: str
) -> None:
    plant(tree, "src/labhq/runs/env.py", f"import os\n{line}\n")

    result = run_guard(tree)

    assert result.returncode == 1
    assert "src/labhq/runs/env.py:2:" in result.stdout
    assert pattern_name in result.stdout


def test_credential_reference_in_migrations_fails(tree: Path) -> None:
    plant(tree, "migrations/versions/0001_init.py", "# copy CLAUDE_CODE_OAUTH_TOKEN\n")

    result = run_guard(tree)

    assert result.returncode == 1
    assert "migrations/versions/0001_init.py:1:" in result.stdout


@pytest.mark.parametrize(
    "line",
    [
        'env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]',
        "anthropic_api_key: SecretStr | None = None",
    ],
)
def test_anthropic_api_key_passes(tree: Path, line: str) -> None:
    plant(tree, "src/labhq/runs/env.py", f"{line}\n")

    result = run_guard(tree)

    assert result.returncode == 0, result.stdout


def test_bytecode_caches_are_skipped(tree: Path) -> None:
    plant(tree, "src/labhq/__pycache__/env.cpython-312.pyc", "CLAUDE_CODE_OAUTH_TOKEN")

    result = run_guard(tree)

    assert result.returncode == 0, result.stdout


def test_missing_root_fails_instead_of_passing_silently(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")

    result = run_guard(tmp_path)

    assert result.returncode == 2
    assert "not a directory: migrations" in result.stderr


def test_empty_roots_fail(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "migrations").mkdir()

    result = run_guard(tmp_path)

    assert result.returncode == 2
    assert "no files" in result.stderr
