from pathlib import Path

import pytest

from tools import single_head

REPO_ROOT = Path(__file__).resolve().parents[2]

REVISION = """
revision = "{rev}"
down_revision = {down}
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
"""


def _scripts(root: Path, revisions: dict[str, str | None]) -> Path:
    versions = root / "migrations" / "versions"
    versions.mkdir(parents=True)
    (root / "migrations" / "script.py.mako").write_text("")
    for rev, down in revisions.items():
        (versions / f"{rev}.py").write_text(REVISION.format(rev=rev, down=repr(down)))
    return root / "migrations"


def test_one_head_passes(tmp_path: Path) -> None:
    migrations = _scripts(tmp_path, {"a": None, "b": "a"})
    assert single_head.main(["--migrations", str(migrations)]) == 0


def test_two_heads_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Two branches each added a migration on top of "a".
    migrations = _scripts(tmp_path, {"a": None, "b": "a", "c": "a"})
    assert single_head.main(["--migrations", str(migrations)]) == 1
    assert "found 2" in capsys.readouterr().out


def test_no_migrations_fail(tmp_path: Path) -> None:
    migrations = _scripts(tmp_path, {})
    assert single_head.main(["--migrations", str(migrations)]) == 1


def test_the_repository_has_one_head() -> None:
    # Not pinned to a revision: every issue that adds a migration moves the head.
    assert len(single_head.heads(REPO_ROOT / "migrations")) == 1
