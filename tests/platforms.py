"""Platform limitations as data, applied in one place (plan §9, ADR 0003).

`@pytest.mark.posix_only("reason")` names a test that fails on native Windows. There it
becomes `xfail(strict=True)`, so a test that starts passing fails the job and its mark has
to go. On Linux and macOS the mark has no effect. `tools/platform_limits.py` lists the marks
in `docs/guide/platforms.md`.

No test is ever skipped: a skip hides a failure, so the session fails on any. Test files
named `test_*_windows.py` exercise Windows itself and are collected only there.

Loaded with `-p tests.platforms` from pyproject.toml, so every run carries it.
"""

import os
from collections.abc import Generator
from pathlib import Path

import pytest

MARKER = "posix_only"
APPLIED = pytest.StashKey[list[str]]()
SKIPPED = pytest.StashKey[list[str]]()


def on_native_windows() -> bool:
    return os.name == "nt"


def limitation_reason(item: pytest.Item) -> str | None:
    mark = item.get_closest_marker(MARKER)
    if mark is None:
        return None
    reason = mark.args[0] if len(mark.args) == 1 and not mark.kwargs else None
    if not isinstance(reason, str) or not reason.strip():
        raise pytest.UsageError(f"{item.nodeid}: {MARKER} takes exactly one non-empty reason")
    return reason


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{MARKER}(reason): a known native Windows limitation, xfail(strict=True) there",
    )
    config.stash[APPLIED] = []
    config.stash[SKIPPED] = []


def pytest_ignore_collect(collection_path: Path) -> bool | None:
    name = collection_path.name
    if name.startswith("test_") and name.endswith("_windows.py") and not on_native_windows():
        return True
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        reason = limitation_reason(item)
        if reason is None or not on_native_windows():
            continue
        item.add_marker(pytest.mark.xfail(reason=f"native Windows: {reason}", strict=True))
        config.stash[APPLIED].append(item.nodeid)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    # An xfail is reported as skipped too; only a real skip carries no `wasxfail`.
    if report.skipped and not hasattr(report, "wasxfail"):
        item.config.stash[SKIPPED].append(item.nodeid)
    return report


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    if session.config.stash.get(SKIPPED, []):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    skipped = config.stash.get(SKIPPED, [])
    if not skipped:
        return
    terminalreporter.section("skipped tests are not allowed", red=True)
    terminalreporter.line(f"Mark a native Windows limitation with {MARKER}(reason) instead:")
    for nodeid in skipped:
        terminalreporter.line(f"  {nodeid}")
