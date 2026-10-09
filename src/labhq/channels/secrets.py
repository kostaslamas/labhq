"""Channel secrets (a bot token), kept owner-only in the data directory, never in the database.

The database holds a channel's non-secret settings and is backed up and queried freely; a
token there would travel with every copy of it. A secret is written once at creation, read
only to build the notifier, and removed with the channel. It is never returned by the API,
printed, logged or put in an error.
"""

import contextlib
import json
import os
from pathlib import Path

DIRECTORY = "channels"
FILE_MODE = 0o600
DIRECTORY_MODE = 0o700


def _path(data_dir: Path, channel_id: int) -> Path:
    return data_dir / DIRECTORY / f"{channel_id}.json"


def write_secrets(data_dir: Path, channel_id: int, values: dict[str, str]) -> None:
    if not values:
        return
    path = _path(data_dir, channel_id)
    path.parent.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    # Created owner-only, so the secret is never readable by others, not even briefly.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(values, handle)


def read_secrets(data_dir: Path, channel_id: int) -> dict[str, str]:
    try:
        stored = json.loads(_path(data_dir, channel_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}
    return {str(key): value for key, value in stored.items() if isinstance(value, str)}


def delete_secrets(data_dir: Path, channel_id: int) -> None:
    with contextlib.suppress(FileNotFoundError):
        _path(data_dir, channel_id).unlink()
