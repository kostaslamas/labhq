"""The ntfy topic is the only secret of a topic subscription, so it is random and kept."""

import secrets
from pathlib import Path

TOPIC_FILENAME = "ntfy_topic"


def load_or_create_topic(data_dir: Path) -> str:
    path = data_dir / TOPIC_FILENAME
    if path.exists():
        topic = path.read_text(encoding="utf-8").strip()
        if topic:
            return topic
    topic = f"labhq-{secrets.token_urlsafe(18)}"
    data_dir.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.write_text(topic + "\n", encoding="utf-8")
    return topic
