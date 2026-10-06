"""The prompt section of a generic department's agents: the kind's text and the shared rules."""

from typing import Any

from labhq.db.models import Agent, Task

DEPARTMENT_SECTION = "department"
# After the role instruction (100), before the output style (200).
DEPARTMENT_POSITION = 150

_RULES = """\
- No git here: no branches, no worktrees. Each task names its deliverable: `document` (save it
  with `write_document`), `report` or `decision` (put it in `report_task`).
- Your head reviews your work and the CEO accepts the department's.
- Email, messages to third parties, publishing, payments and sign-ups are the owner's: ask with
  `request_outward_action`. Nothing happens until the owner approves it with a passkey."""


def department_section(agent: Agent, task: Task | None) -> str | None:
    # Imported here: the department kinds import the hierarchy, which reaches the run service
    # and so this package at load time.
    from labhq.departments import default_kinds
    from labhq.hierarchy.team import DEPARTMENT_KEY
    from labhq.work.deliverables import BRANCH

    info: Any = agent.config.get(DEPARTMENT_KEY)
    if not isinstance(info, dict) or info.get("kind") not in default_kinds:
        return None
    kind = default_kinds.get(info["kind"])
    lines = [
        f"You work in the {info.get('name')} department; its folder is {info.get('folder')}.",
        kind.instructions,
    ]
    if kind.skills:
        lines.append(f"Skills: {', '.join(kind.skills)}.")
    lines.append(_RULES)
    if task is not None and task.deliverable != BRANCH:
        lines.append(f"This task's deliverable is a {task.deliverable}.")
    return "\n".join(lines)
