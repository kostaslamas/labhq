"""Aider keeps its history inside the project, so it is found in folders already known."""

from pathlib import Path

from labhq.inventory.model import SavedEntry
from labhq.inventory.stores.files import modified

HISTORY_FILE = ".aider.chat.history.md"


def aider_entries(tool: str, folders: tuple[Path, ...]) -> list[SavedEntry]:
    found = []
    for folder in dict.fromkeys(folders):
        path = folder / HISTORY_FILE
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            continue
        found.append(SavedEntry(tool, HISTORY_FILE, folder, modified(path), path))
    return found
