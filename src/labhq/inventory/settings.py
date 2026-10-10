"""Session inventory settings, from `LABHQ_INVENTORY_*`. Thresholds and prices are data."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InventorySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_INVENTORY_", extra="ignore")

    # A running agent quiet this long is proposed for closing.
    idle_close_hours: float = Field(default=12.0, gt=0)
    # A saved conversation older than this is kept as history, not continued.
    history_days: float = Field(default=14.0, gt=0)
    # How long the process table is sampled to tell a working agent from a quiet one.
    sample_seconds: float = Field(default=0.5, ge=0)
    # CPU seconds per sample above which a process counts as working.
    busy_cpu_seconds: float = Field(default=0.05, ge=0)
    # The folders the scan may look in; `~` is expanded. A session counts only if its working
    # directory is inside one (symlinks and `..` resolved). Empty means machine-wide. Roots the
    # owner adds with `labhq sessions roots add` or in the web UI are kept in the database and
    # join these.
    roots: list[str] = Field(default_factory=list)
    # Folders or glob patterns inside the roots that the scan skips, for example `~/Developer/old`.
    exclude: list[str] = Field(default_factory=list)
    # How many folders below a root project discovery descends (the root is depth 0).
    discovery_depth: int = Field(default=3, ge=0)
    # The most folders one discovery walk lists; a walk the cap stops is reported as capped.
    discovery_max_folders: int = Field(default=20_000, gt=0)
    # File names that make a folder a project, with the label shown for each. A `.git` entry
    # (folder or file) always does.
    project_markers: dict[str, str] = Field(
        default_factory=lambda: {
            "pyproject.toml": "Python",
            "package.json": "Node",
            "Cargo.toml": "Rust",
            "go.mod": "Go",
            "pom.xml": "Java",
            "Gemfile": "Ruby",
            "composer.json": "PHP",
        }
    )
    # Folders discovery never enters, besides every hidden folder.
    discovery_skip_dirs: list[str] = Field(
        default_factory=lambda: [
            "node_modules",
            ".venv",
            "venv",
            "__pycache__",
            "dist",
            "build",
            "target",
            ".cache",
        ]
    )
    # Minutes between automatic scans while labhq serves; 0 keeps them off. A scan that finds
    # projects labhq does not have raises one notification per new set, at most one a day.
    auto_scan_minutes: int = Field(default=0, ge=0)
    # Where onboarding looks for the folder that holds the owner's projects; the first that
    # exists is offered as a suggestion, never applied by itself.
    suggested_roots: list[str] = Field(
        default_factory=lambda: ["~/Developer", "~/projects", "~/code", "~/src"]
    )
    # Folders searched for tools that keep a history file inside the project (Aider), besides
    # every folder another tool or a running agent already named. Kept inside the scope.
    extra_roots: list[str] = Field(default_factory=list)
    # A parent folder with at least this many projects gets a folder-manager proposal.
    folder_manager_min_projects: int = Field(default=2, ge=2)
    # Ask GitHub for the open pull request of a branch, if `gh` is logged in.
    use_gh: bool = True
    command_timeout_seconds: float = Field(default=15.0, gt=0)
    # Analysis: who may run it, cheapest first; kinds that made the project's sessions come
    # last (or never, see `allow_original_tool`). A name is an agent kind or `ollama`.
    analysis_kind_order: list[str] = Field(
        default_factory=lambda: ["ollama", "gemini", "codex", "opencode", "claude-code"]
    )
    allow_original_tool: bool = False
    # Kinds that need no login (a model on this machine).
    no_login_kinds: list[str] = Field(default_factory=lambda: ["ollama"])
    # What an estimate assumes a million tokens cost on each kind, in micro-USD (ADR 0002).
    # A kind not listed is priced at the default.
    price_per_million_tokens_micros: dict[str, int] = Field(
        default_factory=lambda: {"ollama": 0, "gemini": 1_000_000, "codex": 3_000_000}
    )
    default_price_per_million_micros: int = Field(default=5_000_000, ge=0)
    # Size bounds of what one analysis reads.
    transcript_tail_chars: int = Field(default=6_000, gt=0)
    git_log_commits: int = Field(default=30, gt=0)
    diff_chars: int = Field(default=20_000, gt=0)
    code_chars: int = Field(default=40_000, gt=0)
    chars_per_token: int = Field(default=4, gt=0)
    # The estimate adds this share to cover the model's own reply and tool use.
    reply_tokens: int = Field(default=4_000, ge=0)


@lru_cache(maxsize=1)
def get_inventory_settings() -> InventorySettings:
    return InventorySettings()
