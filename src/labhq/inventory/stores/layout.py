"""Where each tool keeps its conversations: one row per tool, read by a format reader.

A row names the directories to look in (`Root`) and the reader that understands the files
there. A reader returns ids, folders and times only, never message text. A new tool is a new
row here and, when its files are in a new format, a new entry in `FORMATS`; the scanner
branches on neither.

Credential files are never opened: a reader opens exactly the files its format names, and
the stores that hold a login in the same file (Cursor's) select only the chat keys.
"""

import os
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from labhq.inventory.model import SavedEntry


@dataclass(frozen=True)
class Bases:
    """The per-user directories a tool's store hangs off, for the running platform."""

    home: Path
    data: Path
    config: Path

    @classmethod
    def for_user(
        cls, home: Path | None = None, environ: Mapping[str, str] | None = None
    ) -> "Bases":
        env = os.environ if environ is None else environ
        home = home or Path.home()
        if sys.platform == "darwin":
            support = home / "Library" / "Application Support"
            return cls(home, Path(env.get("XDG_DATA_HOME", home / ".local" / "share")), support)
        if sys.platform == "win32":
            roaming = Path(env.get("APPDATA", home / "AppData" / "Roaming"))
            local = Path(env.get("LOCALAPPDATA", home / "AppData" / "Local"))
            return cls(home, local, roaming)
        return cls(
            home,
            Path(env.get("XDG_DATA_HOME", home / ".local" / "share")),
            Path(env.get("XDG_CONFIG_HOME", home / ".config")),
        )


@dataclass(frozen=True)
class Root:
    """A directory: `base` (home, data or config) plus `parts`, or the path in `env`."""

    base: str
    parts: tuple[str, ...]
    # A variable that moves the store; its value replaces base and parts (plus `env_parts`).
    env: str | None = None
    env_parts: tuple[str, ...] = ()

    def resolve(self, bases: Bases, environ: Mapping[str, str]) -> Path:
        if self.env and environ.get(self.env):
            return Path(environ[self.env]).joinpath(*self.env_parts)
        base: Path = getattr(bases, self.base)
        return base.joinpath(*self.parts)


@dataclass(frozen=True)
class Context:
    bases: Bases
    environ: Mapping[str, str]
    # Folders to check for stores that live inside a project (Aider).
    folders: tuple[Path, ...] = ()


@dataclass(frozen=True)
class StoreLayout:
    tool: str
    format: str
    roots: tuple[Root, ...] = ()
    # Names the format needs (a glob, a table, a key); the format documents which.
    options: Mapping[str, str] = field(default_factory=dict)


Reader = Callable[[StoreLayout, Path], Iterator[SavedEntry]]
FORMATS: dict[str, Reader] = {}


def register_format(name: str) -> Callable[[Reader], Reader]:
    def add(reader: Reader) -> Reader:
        if name in FORMATS:
            raise ValueError(f"store format {name!r} is already registered")
        FORMATS[name] = reader
        return reader

    return add


LAYOUTS: dict[str, StoreLayout] = {}


def register_layout(layout: StoreLayout) -> StoreLayout:
    if layout.tool in LAYOUTS:
        raise ValueError(f"store layout for {layout.tool!r} is already registered")
    LAYOUTS[layout.tool] = layout
    return layout


def read_all(context: Context, tools: set[str] | None = None) -> list[SavedEntry]:
    """Every saved conversation of every registered tool (or of `tools`), on this machine."""
    entries: dict[tuple[str, str, Path], SavedEntry] = {}
    for layout in LAYOUTS.values():
        if tools is not None and layout.tool not in tools:
            continue
        reader = FORMATS[layout.format]
        for root in layout.roots:
            path = root.resolve(context.bases, context.environ)
            if path.is_dir() or path.is_file():
                for entry in _safe(reader(layout, path)):
                    entries.setdefault((entry.tool, entry.session_id, entry.folder), entry)
    return list(entries.values())


def _safe(entries: Iterator[SavedEntry]) -> Iterator[SavedEntry]:
    # A store that changes under the reader, or one in a version it does not know, must not
    # hide the other tools' sessions.
    try:
        yield from entries
    except (OSError, ValueError):
        return
