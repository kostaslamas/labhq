"""Native Windows only (collected there alone, see tests/platforms.py): `taskkill /T` stops
a real process tree, grandchildren included."""

import contextlib
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass

import psutil
import pytest

from labhq.scheduler import WindowsTaskkillTerminator, default_terminators

# The parent waits on its child, so the child only dies if the whole tree is stopped.
CHILD = "import threading; threading.Event().wait(600)"
PARENT = (
    "import subprocess, sys\n"
    f"child = subprocess.Popen([sys.executable, '-c', {CHILD!r}])\n"
    "print(child.pid, flush=True)\n"
    "child.wait()\n"
)
GONE_WITHIN = 30


@dataclass
class Tree:
    root: subprocess.Popen[str]
    # Every descendant, so a venv launcher between python and its child counts too.
    descendants: list[psutil.Process]


@pytest.fixture
def tree() -> Iterator[Tree]:
    terminator = WindowsTaskkillTerminator()
    root = subprocess.Popen(
        [sys.executable, "-c", PARENT],
        stdout=subprocess.PIPE,
        text=True,
        **terminator.popen_options(),
    )
    assert root.stdout is not None
    descendants: list[psutil.Process] = []
    try:
        child = psutil.Process(int(root.stdout.readline()))
        descendants = psutil.Process(root.pid).children(recursive=True)
        assert child in descendants
        yield Tree(root, descendants)
    finally:
        # psutil checks each process is still the one it saw, so a reused PID is safe.
        for process in descendants:
            with contextlib.suppress(psutil.NoSuchProcess):
                process.kill()
        root.kill()
        root.wait(GONE_WITHIN)
        root.stdout.close()


def assert_tree_is_gone(tree: Tree) -> None:
    tree.root.wait(GONE_WITHIN)
    gone, alive = psutil.wait_procs(tree.descendants, timeout=GONE_WITHIN)
    assert alive == []
    assert len(gone) == len(tree.descendants)


def test_the_default_terminator_on_windows_is_taskkill() -> None:
    assert isinstance(default_terminators.create(), WindowsTaskkillTerminator)


def test_kill_stops_the_whole_tree(tree: Tree) -> None:
    assert WindowsTaskkillTerminator().kill(tree.root.pid)
    assert_tree_is_gone(tree)


def test_terminate_then_kill_stops_the_whole_tree(tree: Tree) -> None:
    terminator = WindowsTaskkillTerminator()
    # Console processes refuse a graceful close; the caller's escalation must still win.
    assert terminator.terminate(tree.root.pid)
    terminator.kill(tree.root.pid)
    assert_tree_is_gone(tree)


def test_a_tree_that_is_already_gone_reports_false(tree: Tree) -> None:
    terminator = WindowsTaskkillTerminator()
    terminator.kill(tree.root.pid)
    assert_tree_is_gone(tree)
    assert not terminator.kill(tree.root.pid)
    assert not terminator.terminate(tree.root.pid)
