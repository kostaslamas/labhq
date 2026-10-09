"""The store layouts of every supported tool, as data rows (see `layout`)."""

from labhq.inventory.stores import cursor, files, opencode  # noqa: F401  (register formats)
from labhq.inventory.stores.aider import aider_entries
from labhq.inventory.stores.layout import (
    LAYOUTS,
    Bases,
    Context,
    Root,
    StoreLayout,
    read_all,
    register_layout,
)

CURSOR_IDE = "cursor-ide"
AIDER = "aider"

for _layout in (
    StoreLayout(
        "claude-code",
        "jsonl-cwd-field",
        (Root("home", (".claude", "projects"), env="CLAUDE_CONFIG_DIR", env_parts=("projects",)),),
        {"glob": "*/*.jsonl"},
    ),
    StoreLayout(
        "codex",
        "jsonl-meta-row",
        (Root("home", (".codex", "sessions"), env="CODEX_HOME", env_parts=("sessions",)),),
        {"glob": "**/rollout-*.jsonl"},
    ),
    StoreLayout(
        "gemini",
        "gemini-marker",
        (Root("home", (".gemini", "tmp"), env="GEMINI_CLI_HOME", env_parts=("tmp",)),),
        {"glob": "chats/session-*.json"},
    ),
    StoreLayout(
        "opencode",
        "opencode-sqlite",
        (
            Root("home", (), env="OPENCODE_DB"),
            Root(
                "home",
                (".local", "share", "opencode"),
                env="XDG_DATA_HOME",
                env_parts=("opencode",),
            ),
        ),
        {"file": "opencode.db"},
    ),
    StoreLayout(
        "cursor-agent",
        "cursor-cli-meta",
        (Root("home", (".cursor", "chats")),),
        {"glob": "*/*/meta.json"},
    ),
    StoreLayout(CURSOR_IDE, "cursor-ide-vscdb", (Root("config", ("Cursor", "User")),)),
):
    register_layout(_layout)

__all__ = [
    "AIDER",
    "CURSOR_IDE",
    "LAYOUTS",
    "Bases",
    "Context",
    "Root",
    "StoreLayout",
    "aider_entries",
    "read_all",
]
