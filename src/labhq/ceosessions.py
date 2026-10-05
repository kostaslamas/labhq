"""Stable names and operational skill for the global CEO's CLI sessions."""

import re
from pathlib import Path

SKILL_RELATIVE_PATH = Path(".labhq/skills/ceo-operations/SKILL.md")
SKILL_SOURCE = Path(__file__).parent / "roles/skills/ceo-operations/SKILL.md"
CEO_ROLE = "ceo"


def ceo_session_name(kind: str) -> str:
    """The private tmux pane of one CEO CLI kind, e.g. ceo_claude or ceo_codex."""
    label = "claude" if kind == "claude-code" else re.sub(r"[^a-z0-9]+", "_", kind.lower())
    return f"ceo_{label.strip('_')}"


def install_ceo_skill(home: Path, socket: str) -> Path:
    """Keep the app-owned skill beside the CEO's durable memory."""
    destination = home / SKILL_RELATIVE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = SKILL_SOURCE.read_text(encoding="utf-8").replace("{socket}", socket)
    if not destination.exists() or destination.read_text(encoding="utf-8") != text:
        destination.write_text(text, encoding="utf-8")
    return destination
