"""A fake extractor: canned answers per captured screen, so no test calls a model."""

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).with_name("fixtures")

# What a well-behaved extractor answers for each captured screen, numbers copied verbatim.
ANSWERS: dict[str, dict[str, Any]] = {
    "codex_status.txt": {
        "readings": [
            {"unit": "percent", "value": 31, "window": "5h", "resets_at": "2026-10-02T17:42:00Z"},
            {
                "unit": "percent",
                "value": 14,
                "window": "weekly",
                "resets_at": "2026-10-08T09:00:00Z",
            },
        ],
        "limit_notice": False,
    },
    "gemini_stats.txt": {
        "readings": [
            {"unit": "percent", "value": 18, "window": "daily", "resets_at": "2026-10-03T04:04:00Z"}
        ],
        "limit_notice": False,
    },
    "aider_reply.txt": {
        "readings": [
            {"unit": "usd", "value": 0.07, "window": "session"},
            {"unit": "tokens", "value": 611, "window": "received"},
        ],
        "limit_notice": False,
    },
    "claude_limit_notice.txt": {
        "readings": [],
        "limit_notice": True,
        "limit_resets_at": "2026-10-02T15:00:00Z",
    },
}


def screen(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeExtractor:
    """Answers with a fixed JSON text and records what it was shown."""

    def __init__(self, answer: dict[str, Any] | str) -> None:
        self.answer = answer if isinstance(answer, str) else json.dumps(answer)
        self.seen: list[tuple[str, str]] = []

    async def extract(self, captured: str, agent_kind: str) -> str:
        self.seen.append((captured, agent_kind))
        return f"Here is the JSON:\n```json\n{self.answer}\n```"
