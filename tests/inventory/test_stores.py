"""Every tool's store is read from its real layout: ids, folders and times, nothing else."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from labhq.inventory.stores import Bases, Context, aider_entries, read_all
from tests.inventory import stores_fixture as fx


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def entries(home: Path, **env: str) -> dict[tuple[str, str], Path]:
    context = Context(Bases.for_user(home, env), env)
    return {(e.tool, e.session_id): e.folder for e in read_all(context)}


def test_each_file_store_yields_its_session_and_folder(home: Path, tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in "abc")
    fx.claude(home, a)
    fx.codex(home, b)
    fx.gemini(home, c)

    assert entries(home) == {
        ("claude-code", fx.CLAUDE_ID): a,
        ("codex", fx.CODEX_ID): b,
        ("gemini", fx.GEMINI_ID): c,
    }


def test_aider_is_found_in_the_folders_it_is_told_about(tmp_path: Path) -> None:
    (tmp_path / "with").mkdir()
    fx.aider(tmp_path / "with")
    (tmp_path / "without").mkdir()

    found = aider_entries("aider", (tmp_path / "with", tmp_path / "without"))

    assert [(e.tool, e.folder) for e in found] == [("aider", tmp_path / "with")]


def test_opencode_skips_archived_child_and_folderless_sessions(home: Path, tmp_path: Path) -> None:
    fx.opencode(
        home,
        [
            ("ses_live", str(tmp_path / "p"), None, None),
            ("ses_archived", str(tmp_path / "p"), None, 1),
            ("ses_child", str(tmp_path / "p"), "ses_live", None),
            ("ses_nowhere", "", None, None),
        ],
    )

    assert entries(home) == {("opencode", "ses_live"): tmp_path / "p"}


def test_opencode_follows_xdg_data_home(tmp_path: Path) -> None:
    data = tmp_path / "elsewhere"
    fx.opencode(data.parent / "x", [("ses_a", "/w", None, None)])
    moved = data / "opencode"
    moved.mkdir(parents=True)
    (tmp_path / "x" / ".local" / "share" / "opencode" / "opencode.db").rename(moved / "opencode.db")

    assert entries(tmp_path / "nohome", XDG_DATA_HOME=str(data)) == {
        ("opencode", "ses_a"): Path("/w")
    }


def test_cursor_cli_reads_meta_json_and_skips_chats_without_a_folder(
    home: Path, tmp_path: Path
) -> None:
    fx.cursor_cli(home, "chat-1", {"cwd": str(tmp_path / "p"), "updatedAtMs": fx.EPOCH_MS})
    fx.cursor_cli(home, "chat-2", {"updatedAtMs": fx.EPOCH_MS})
    fx.cursor_cli(home, "chat-3", None, store=False)
    fx.cursor_cli(home, "chat-4", {"cwd": str(tmp_path / "q"), "hasConversation": False})

    assert entries(home) == {("cursor-agent", "chat-1"): tmp_path / "p"}


def test_cursor_cli_accepts_microsecond_and_text_times(home: Path, tmp_path: Path) -> None:
    fx.cursor_cli(home, "us", {"cwd": "/w", "updatedAtMs": fx.EPOCH_MS * 1000})
    fx.cursor_cli(home, "iso", {"cwd": "/w", "updatedAtMs": "2026-05-28T00:00:00Z"})
    context = Context(Bases.for_user(home, {}), {})

    times = {e.session_id: e.updated_at for e in read_all(context)}

    expected = datetime.fromtimestamp(fx.EPOCH_MS / 1000, tz=UTC)
    assert times["us"] == expected
    assert times["iso"] == datetime(2026, 5, 28, tzinfo=UTC)


def test_cursor_ide_reads_the_chat_index_and_times_from_sqlite(home: Path, tmp_path: Path) -> None:
    fx.cursor_ide(
        home,
        {"c1": (tmp_path / "p", fx.EPOCH_MS + 9), "c2": (None, fx.EPOCH_MS)},
        legacy=tmp_path / "old",
    )
    context = Context(Bases.for_user(home, {}), {})

    found = {e.session_id: e for e in read_all(context) if e.tool == "cursor-ide"}

    assert set(found) == {"c1", "legacy-chat"}
    assert found["c1"].folder == tmp_path / "p"
    assert found["c1"].updated_at == datetime.fromtimestamp((fx.EPOCH_MS + 9) / 1000, tz=UTC)
    assert found["legacy-chat"].folder == tmp_path / "old"


def test_a_corrupt_store_does_not_hide_the_others(home: Path, tmp_path: Path) -> None:
    fx.claude(home, tmp_path / "a")
    database = home / ".local" / "share" / "opencode" / "opencode.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"not a database")

    assert entries(home) == {("claude-code", fx.CLAUDE_ID): tmp_path / "a"}


def test_the_chat_stores_are_opened_read_only(home: Path, tmp_path: Path) -> None:
    path = fx.opencode(home, [("ses_a", "/w", None, None)])
    before = path.stat().st_mtime_ns

    entries(home)

    assert path.stat().st_mtime_ns == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM session").fetchone() == (1,)
