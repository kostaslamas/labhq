"""A labhq manager's rules (ADR 0005) and the routes that deliver them.

The rules always go to `.labhq/rules.md`, under the `.labhq/` entry of the repository's
`info/exclude`, so `git add -A` never stages them. The owner's tracked files, `CLAUDE.md`
included, are never changed.
"""

from pathlib import Path

from labhq.adapters.tmux import AgentKind, RulesInjection
from labhq.worktrees.exclude import STATE_DIR, exclude_state_dir

RULES_RELATIVE_PATH = Path(STATE_DIR) / "rules.md"

MANAGER_RULES: tuple[str, ...] = (
    "Update .labhq/status.md at the end of every turn: summary, done, next, blockers, refs, "
    "questions.",
    "Make no more code edits in this checkout: split the work into tasks for workers, who "
    "work in their own worktrees.",
    "Never push or merge: request an approval.",
    "Be terse with agents and natural with the owner.",
    "Ask the owner through the questions field of .labhq/status.md, not by waiting at the "
    "terminal.",
)

STATUS_REQUEST = (
    "labhq: your last turn ended without an update to .labhq/status.md. Update it now, as "
    ".labhq/rules.md says."
)

# (in the system prompt on every start, as a message after the move and each compaction)
ROUTES: dict[RulesInjection, tuple[bool, bool]] = {
    RulesInjection.SYSTEM_PROMPT: (True, False),
    RulesInjection.FIRST_MESSAGE: (False, True),
    RulesInjection.BOTH: (True, True),
}


def appends(kind: AgentKind) -> bool:
    return ROUTES[kind.rules_injection][0]


def sends(kind: AgentKind) -> bool:
    return ROUTES[kind.rules_injection][1]


def rules_text() -> str:
    lines = "".join(f"- {rule}\n" for rule in MANAGER_RULES)
    return f"# labhq manager rules\n\nYou are this project's manager under labhq.\n\n{lines}"


def rules_message() -> str:
    """The rules as one line: a newline typed into an agent's prompt would send it early."""
    numbered = " ".join(f"{index}) {rule}" for index, rule in enumerate(MANAGER_RULES, 1))
    return (
        "labhq: you are now this project's manager under labhq. Follow these rules, also in "
        f".labhq/rules.md: {numbered}"
    )


def write_rules(checkout: Path) -> Path:
    """Exclude `.labhq/` first, then write the rules, so nothing can stage them in between."""
    exclude_state_dir(checkout)
    path = checkout / RULES_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rules_text(), encoding="utf-8")
    return path
