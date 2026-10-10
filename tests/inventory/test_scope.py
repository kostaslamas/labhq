"""The scan scope: sessions outside the roots are not found, listed or read."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from labhq.inventory.model import Inventory
from labhq.inventory.report import scope_text, spoken
from labhq.inventory.scope import Scope, build_scope
from tests.inventory import stores_fixture as fx
from tests.inventory.conftest import FakeProcess, Scan, make_repo

OUT_CLAUDE = "aaaaaaaa-1111-4111-8111-111111111111"
OUT_CODEX = "bbbbbbbb-2222-4222-8222-222222222222"
OUT_GEMINI = "cccccccc-3333-4333-8333-333333333333"
# Files that hold nothing but the folder a session works in; reading their head is how a
# scan learns that the session is out of scope.
METADATA_FILES = ("meta.json", ".project_root")


@dataclass
class ReadLog:
    """What a scan opened and what the files gave it."""

    opened: list[Path] = field(default_factory=list)
    returned: list[tuple[Path, str]] = field(default_factory=list)
    statements: list[str] = field(default_factory=list)
    armed: bool = False

    @contextmanager
    def watching(self) -> Iterator[None]:
        """Record only the scan, not the fixtures that build the stores."""
        self.armed = True
        try:
            yield
        finally:
            self.armed = False


class Recording:
    def __init__(self, stream: Any, path: Path, log: ReadLog) -> None:
        self._stream, self._path, self._log = stream, path, log

    def __enter__(self) -> "Recording":
        return self

    def __exit__(self, *exc: object) -> None:
        self._stream.close()

    def _note(self, data: Any) -> Any:
        text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
        self._log.returned.append((self._path, text))
        return data

    def readline(self, *args: Any) -> Any:
        return self._note(self._stream.readline(*args))

    def read(self, *args: Any) -> Any:
        return self._note(self._stream.read(*args))

    def __iter__(self) -> Iterator[Any]:
        for line in self._stream:
            yield self._note(line)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> ReadLog:
    """Fails nothing itself; the test reads the log. Covers file opens and SQL statements."""
    log = ReadLog()
    real_open, real_read_text = Path.open, Path.read_text

    def opening(self: Path, *args: Any, **kwargs: Any) -> Any:
        if not log.armed:
            return real_open(self, *args, **kwargs)
        log.opened.append(self)
        return Recording(real_open(self, *args, **kwargs), self, log)

    def reading(self: Path, *args: Any, **kwargs: Any) -> str:
        text = real_read_text(self, *args, **kwargs)
        if log.armed:
            log.opened.append(self)
            log.returned.append((self, text))
        return text

    def connecting(path: Path) -> sqlite3.Connection:
        log.opened.append(path)
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        connection.set_trace_callback(log.statements.append)
        return connection

    monkeypatch.setattr(Path, "open", opening)
    monkeypatch.setattr(Path, "read_text", reading)
    for module in ("opencode", "cursor"):
        monkeypatch.setattr(f"labhq.inventory.stores.{module}.connect_read_only", connecting)
    return log


def is_outside(path: Path) -> bool:
    """One of the out-of-scope conversations' files, by the ids the fixtures gave them."""
    return any(mark in str(path) for mark in (OUT_CLAUDE, OUT_CODEX, "zzz999", "chat-out"))


def ids(inventory: Inventory) -> set[tuple[str, str | None]]:
    return {(s.tool, s.session_id) for p in inventory.projects for s in p.sessions}


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    inside = tmp_path / "dev" / "inside"
    outside = tmp_path / "elsewhere" / "outside"
    inside.mkdir(parents=True)
    outside.mkdir(parents=True)
    return inside, outside


def store_every_tool(home: Path, inside: Path, outside: Path) -> None:
    fx.claude(home, inside)
    fx.claude(home, outside, OUT_CLAUDE)
    fx.codex(home, inside)
    fx.codex(home, outside, OUT_CODEX)
    fx.gemini(home, inside)
    fx.gemini(home, outside, OUT_GEMINI, directory_name="zzz999")
    fx.opencode(home, [("ses_in", str(inside), None, None), ("ses_out", str(outside), None, None)])
    fx.cursor_cli(home, "chat-in", {"cwd": str(inside), "updatedAtMs": fx.EPOCH_MS})
    fx.cursor_cli(home, "chat-out", {"cwd": str(outside), "updatedAtMs": fx.EPOCH_MS})
    fx.cursor_ide(home, {"comp-in": (inside, fx.EPOCH_MS), "comp-out": (outside, fx.EPOCH_MS)})
    fx.aider(inside)
    fx.aider(outside)


def test_a_session_outside_the_roots_is_absent_and_its_conversation_never_read(
    home: Path, folders: tuple[Path, Path], scanner: Scan, spy: ReadLog
) -> None:
    inside, outside = folders
    store_every_tool(home, inside, outside)
    running = [FakeProcess(5, ["claude"], inside), FakeProcess(6, ["codex"], outside)]

    with spy.watching():
        inventory = scanner(running, roots=[str(inside.parent)]).scan()

    found = ids(inventory)
    assert {tool for tool, _ in found} == {
        "claude-code",
        "codex",
        "gemini",
        "opencode",
        "cursor-agent",
        "cursor-ide",
        "aider",
    }
    assert not {OUT_CLAUDE, OUT_CODEX, OUT_GEMINI, "ses_out", "chat-out", "comp-out"} & {
        i for _, i in found
    }
    assert {s.folder for p in inventory.projects for s in p.sessions} == {inside}
    # Six saved sessions plus the running codex, a number and no path.
    assert inventory.left_out == 7
    assert inventory.roots == (inside.parent.resolve(),)

    # Nothing outside was read: a conversation file is not opened, and a file that only
    # names the folder gave up nothing but that.
    turned_away = [p for p in spy.opened if is_outside(p)]
    assert all(p.name in METADATA_FILES or p.name.startswith("rollout-") for p in turned_away)
    leaked = [path for path, text in spy.returned if fx.SECRET_TEXT in text and is_outside(path)]
    assert leaked == []
    assert not any("comp-out" in sql or "ses_out" in sql for sql in spy.statements)
    assert not any("FROM message" in sql for sql in spy.statements)


def test_a_claude_conversation_outside_the_roots_is_not_even_opened(
    home: Path, folders: tuple[Path, Path], scanner: Scan, spy: ReadLog
) -> None:
    inside, outside = folders
    store_every_tool(home, inside, outside)

    with spy.watching():
        scanner(roots=[str(inside)]).scan()

    assert not [p for p in spy.opened if p.suffix == ".jsonl" and OUT_CLAUDE in p.name]


def test_a_symlink_or_dot_dot_cannot_lead_out_of_a_root(
    home: Path, folders: tuple[Path, Path], scanner: Scan
) -> None:
    inside, outside = folders
    root = inside.parent
    (root / "link").symlink_to(outside, target_is_directory=True)
    sneaky = root / "inside" / ".." / ".." / "elsewhere" / "outside"
    fx.opencode(
        home,
        [
            ("ses_ok", str(inside), None, None),
            ("ses_link", str(root / "link"), None, None),
            ("ses_dots", str(sneaky), None, None),
        ],
    )

    inventory = scanner(roots=[str(root)]).scan()

    assert ids(inventory) == {("opencode", "ses_ok")}
    assert inventory.left_out == 2


def test_a_root_given_as_a_symlink_is_compared_on_its_real_path(
    tmp_path: Path, folders: tuple[Path, Path]
) -> None:
    inside, _ = folders
    alias = tmp_path / "alias"
    alias.symlink_to(inside.parent, target_is_directory=True)

    scope = build_scope([alias], [])

    assert scope.contains(inside)
    assert scope.contains(alias / "inside")
    assert not scope.contains(tmp_path / "elsewhere")


def test_excluded_folders_and_patterns_remove_the_sessions_inside_them(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    root = tmp_path / "dev"
    keep, old, vendored = root / "app", root / "old" / "x", root / "app2" / "vendor"
    for folder in (keep, old, vendored):
        folder.mkdir(parents=True)
    fx.opencode(
        home,
        [(f"ses_{i}", str(f), None, None) for i, f in enumerate((keep, old, vendored))],
    )

    inventory = scanner(roots=[str(root)], exclude=[str(root / "old"), f"{root}/*/vendor"]).scan()

    assert ids(inventory) == {("opencode", "ses_0")}
    assert inventory.left_out == 2


def test_with_no_roots_the_scan_is_machine_wide_and_says_so(
    home: Path, folders: tuple[Path, Path], scanner: Scan
) -> None:
    inside, outside = folders
    store_every_tool(home, inside, outside)

    inventory = scanner().scan()

    assert {OUT_CLAUDE, "ses_out"} <= {i for _, i in ids(inventory)}
    assert inventory.roots == () and inventory.left_out == 0
    assert scope_text(inventory) == "machine-wide: no scope set"
    assert spoken(inventory).endswith("(machine-wide: no scope set)")


def test_the_spoken_report_names_the_roots_and_counts_the_rest_without_paths(
    home: Path, folders: tuple[Path, Path], scanner: Scan
) -> None:
    inside, outside = folders
    store_every_tool(home, inside, outside)

    text = spoken(scanner(roots=[str(inside.parent)]).scan())

    assert str(inside.parent) in text
    assert "6 sessions left out" in text
    assert str(outside) not in text


def test_folder_manager_proposals_only_consider_parents_inside_the_roots(
    home: Path, tmp_path: Path, scanner: Scan, make_ids: Callable[[], str]
) -> None:
    mine = [make_repo(tmp_path / "dev" / "games" / n) for n in ("party", "chess")]
    theirs = [make_repo(tmp_path / "work" / "clients" / n) for n in ("a", "b")]
    for folder in (*mine, *theirs):
        fx.claude(home, folder, make_ids())

    wide = scanner().scan()
    narrow = scanner(roots=[str(tmp_path / "dev")]).scan()

    assert {f.folder for f in wide.folders} == {
        tmp_path / "dev" / "games",
        tmp_path / "work" / "clients",
    }
    assert [f.folder for f in narrow.folders] == [tmp_path / "dev" / "games"]


def test_the_aider_search_uses_the_roots_and_stays_inside_them(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    inside, extra = tmp_path / "dev" / "app", tmp_path / "far" / "app"
    inside.mkdir(parents=True)
    extra.mkdir(parents=True)
    fx.aider(inside)
    fx.aider(extra)

    only_roots = scanner(roots=[str(tmp_path / "dev")]).scan()
    both = scanner(roots=[str(tmp_path / "dev")], extra_roots=[str(extra)]).scan()
    compatible = scanner(extra_roots=[str(extra)]).scan()

    assert {s.folder for p in only_roots.projects for s in p.sessions} == {inside}
    # `extra_roots` stays for compatibility, but never reaches outside a set scope.
    assert {s.folder for p in both.projects for s in p.sessions} == {inside}
    assert {s.folder for p in compatible.projects for s in p.sessions} == {extra}


def test_scope_membership_is_the_real_path(tmp_path: Path) -> None:
    scope = Scope((tmp_path.resolve(),))

    assert scope.contains(tmp_path / "a" / ".." / "b")
    assert not scope.contains(tmp_path / "..")
