"""OpenCode: one SQLite file (`opencode.db`) with a `session` table.

Verified in sst/opencode `packages/core/src/session/sql.ts` and `database/database.ts`:
`directory` is the working folder, `time_updated` is epoch milliseconds, subagent sessions
have a `parent_id` and archived ones a `time_archived`. The message and part tables hold
conversation text and are never queried.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from labhq.inventory.model import SavedEntry
from labhq.inventory.scope import ScopeFilter
from labhq.inventory.stores.layout import StoreLayout, register_format

QUERY = (
    "SELECT id, directory, time_updated FROM session "
    "WHERE time_archived IS NULL AND parent_id IS NULL AND directory <> ''"
)


def connect_read_only(path: Path) -> sqlite3.Connection:
    # `mode=ro` leaves a store another process writes untouched; immutable would miss its WAL.
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2.0)


def from_millis(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


@register_format("opencode-sqlite")
def opencode_sqlite(layout: StoreLayout, root: Path, scope: ScopeFilter) -> Iterator[SavedEntry]:
    database = root / layout.options["file"] if root.is_dir() else root
    if not database.is_file():
        return
    try:
        with closing(connect_read_only(database)) as connection:
            rows = connection.execute(QUERY).fetchall()
    except sqlite3.Error:
        return
    for session_id, directory, updated in rows:
        when = from_millis(updated)
        if not (isinstance(session_id, str) and isinstance(directory, str) and when is not None):
            continue
        if scope.allows(Path(directory)):
            yield SavedEntry(layout.tool, session_id, Path(directory), when, database)
