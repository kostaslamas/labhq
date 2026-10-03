"""Read a task worktree's `.labhq/status.md` and store what changed.

One `status_updates` row per change: the fingerprint is the hash of the parsed fields, so
a rewrite that says the same thing stores nothing. Each question in the file goes through
`raise_question`, which makes it one row and one notification however often it is read.
Ingestion flushes but never commits: the caller owns the transaction.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.questions import raise_question
from labhq.callcenter.status.format import StatusFields, parse_status
from labhq.clock import Clock
from labhq.db.models import AgentQuestion, StatusUpdate

STATUS_RELATIVE_PATH = Path(".labhq") / "status.md"


@dataclass(frozen=True)
class IngestResult:
    update: StatusUpdate | None
    new_questions: list[AgentQuestion] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.update is not None


def status_fingerprint(fields: StatusFields) -> str:
    return hashlib.sha256(fields.model_dump_json().encode("utf-8")).hexdigest()


def read_status_file(worktree: Path) -> tuple[StatusFields, datetime] | None:
    """The parsed file and its modification time (UTC), or None when there is no file."""
    path = worktree / STATUS_RELATIVE_PATH
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except FileNotFoundError:
        return None
    return parse_status(text), modified


async def ingest_status(
    db: AsyncSession,
    clock: Clock,
    *,
    agent_id: int,
    task_id: int | None,
    worktree: Path,
) -> IngestResult:
    """Store the worktree's status if it differs from the agent's last stored one.

    `observed_at` is the file's own modification time, because freshness compares it with
    the agent's last activity; ingesting late must not make an old status look new.
    """
    read = read_status_file(worktree)
    if read is None:
        return IngestResult(None)
    fields, modified = read
    fingerprint = status_fingerprint(fields)
    latest = await db.scalar(
        select(StatusUpdate)
        .where(
            StatusUpdate.agent_id == agent_id, StatusUpdate.task_id.is_not_distinct_from(task_id)
        )
        .order_by(StatusUpdate.id.desc())
        .limit(1)
    )
    if latest is not None and latest.fingerprint == fingerprint:
        return IngestResult(None)
    update = StatusUpdate(
        agent_id=agent_id,
        task_id=task_id,
        fields=fields.model_dump(mode="json"),
        fingerprint=fingerprint,
        observed_at=modified,
    )
    db.add(update)
    new: list[AgentQuestion] = []
    for text in fields.questions:
        question = await raise_question(db, clock, agent_id=agent_id, task_id=task_id, text=text)
        if question is not None:
            new.append(question)
    await db.flush()
    return IngestResult(update, new)
