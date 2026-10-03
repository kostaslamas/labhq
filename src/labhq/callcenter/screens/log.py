"""When each run's screen last changed, kept as a hash of the captured text.

One small file per run under the tmux state directory, because the readers are separate
processes (one stdio server per call, and the engine) and the record is only a hint for
freshness: it needs no transaction and no migration. A file is replaced atomically, so a
reader never sees half a record.
"""

import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ValidationError


class ScreenRecord(BaseModel):
    digest: str
    changed_at: AwareDatetime


def screen_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ScreenLog:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def observe(self, run_id: int, text: str, now: datetime, first_seen: datetime) -> datetime:
        """Record a capture of the run's screen; return when the screen last changed.

        A screen seen for the first time is dated `first_seen`: the tmux adapter records
        every change it polls as a `screen` event, so until labhq reads the pane itself the
        screen is as old as the run's last event.
        """
        digest = screen_digest(text)
        record = self._read(run_id)
        if record is not None and record.digest == digest:
            return record.changed_at
        changed_at = now if record is not None else first_seen
        self._write(run_id, ScreenRecord(digest=digest, changed_at=changed_at))
        return changed_at

    def _path(self, run_id: int) -> Path:
        return self.directory / f"run-{run_id}.json"

    def _read(self, run_id: int) -> ScreenRecord | None:
        try:
            return ScreenRecord.model_validate_json(self._path(run_id).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValidationError):
            return None

    def _write(self, run_id: int, record: ScreenRecord) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(run_id)
        partial = path.with_name(f"{path.name}.{uuid.uuid4().hex}.partial")
        partial.write_text(record.model_dump_json(), encoding="utf-8")
        partial.replace(path)
