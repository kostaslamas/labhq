"""Conversations of the Ollama adapter, kept on disk because Ollama keeps none.

A session is one JSON file named by an id the adapter assigns. `agent_task_sessions` stores
that id like any other adapter's, and a resumed run reloads the messages from here.
"""

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from labhq.adapters.base import AdapterError

Message = dict[str, str]

# Ids are ours, so anything else is a path someone made up: refuse it before it is joined.
_SESSION_ID = re.compile(r"[0-9a-f]{32}")


def new_session_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class StoredSession:
    model: str
    messages: list[Message]


class SessionStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(session_id):
            raise AdapterError(f"{session_id!r} is not an Ollama session id")
        return self.directory / f"{session_id}.json"

    def load(self, session_id: str) -> StoredSession:
        path = self.path_for(session_id)
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise AdapterError(f"no stored Ollama session {session_id}") from None
        return StoredSession(model=str(data["model"]), messages=list(data["messages"]))

    def save(self, session_id: str, session: StoredSession) -> None:
        path = self.path_for(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so an interrupted save never leaves half a conversation.
        partial = path.with_suffix(".json.tmp")
        payload = {"model": session.model, "messages": session.messages}
        partial.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        partial.replace(path)
