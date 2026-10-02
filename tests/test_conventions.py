"""Mechanical checks for conventions that are easy to break by accident."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_WALL_CLOCK_SLEEP = re.compile(
    r"\b(?:time|asyncio)\.sleep\(|from (?:time|asyncio) import .*\bsleep\b"
)
_CREATE_ALL = re.compile(r"\bcreate_all\b")


def _python_files(*roots: str) -> list[Path]:
    return sorted(path for root in roots for path in (REPO_ROOT / root).rglob("*.py"))


def test_the_scans_see_files() -> None:
    # A scan over nothing would pass silently.
    assert _python_files("tests")
    assert _python_files("src", "migrations")


@pytest.mark.parametrize("path", _python_files("tests"), ids=lambda p: p.name)
def test_tests_never_sleep_on_wall_clock_time(path: Path) -> None:
    if path == Path(__file__):
        return
    assert not _WALL_CLOCK_SLEEP.search(path.read_text(encoding="utf-8")), (
        f"{path}: use the FakeClock from labhq.clock instead of sleeping"
    )


def test_application_code_never_calls_create_all() -> None:
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _python_files("src", "migrations")
        if _CREATE_ALL.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], "Alembic migrations are the only schema authority"
