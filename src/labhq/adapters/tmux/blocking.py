"""Screens an interactive agent stops on, and what labhq may do about them.

Each agent kind lists the dialogs it is known to block on, as data. A dialog with
`accept_keys` is a trust question about the working directory: labhq answers it only for a
directory it created itself, never for the owner's own checkouts (ADR 0005). Every other
dialog, or a trust question about any other directory, fails the run with the dialog's
reason; no key is ever sent to a pane for it.
"""

import re
from dataclasses import dataclass
from pathlib import Path

# Dialogs sit at the bottom of the pane; the capture also holds the whole scrollback, where
# a dialog that was answered long ago must not match again.
DIALOG_TAIL_LINES = 15


@dataclass(frozen=True)
class BlockingScreen:
    name: str
    # Matched against the last lines of the pane, `re.DOTALL`.
    pattern: str
    # What the run fails with when the screen is not answered.
    reason: str
    # Keys that answer the dialog in the affirmative; empty means labhq never answers it.
    accept_keys: tuple[str, ...] = ()


def tail_of(screen: str) -> str:
    lines = [line for line in screen.splitlines() if line.strip()]
    return "\n".join(lines[-DIALOG_TAIL_LINES:])


def blocking_screen(screens: tuple[BlockingScreen, ...], screen: str) -> BlockingScreen | None:
    tail = tail_of(screen)
    return next((s for s in screens if re.search(s.pattern, tail, re.DOTALL)), None)


def created_by_labhq(cwd: Path, root: Path | None) -> bool:
    """True only for a directory strictly inside labhq's own data directory.

    Both paths are resolved first, so a symlink in the data directory that points at a
    checkout of the owner's is not labhq's.
    """
    if root is None:
        return False
    real, base = cwd.resolve(), root.resolve()
    return real != base and base in real.parents
