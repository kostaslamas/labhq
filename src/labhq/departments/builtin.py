"""The department kinds labhq ships: IT, migrated from the hand-coded department, and the
generic non-code kinds the CEO can name. A kind is one registration in `default_kinds`."""

from labhq.departments.kinds import DepartmentKind, default_kinds
from labhq.guards.readonly import PERMISSION_MODE_KEY, READ_ONLY_MODE
from labhq.hierarchy import IT
from labhq.prompts.rules import ASK_RULE, STATUS_RULE
from labhq.work.deliverables import DECISION, REPORT

IT_INSTRUCTION = f"""
You are labhq's IT agent. You watch the machines: the one labhq runs on and the hosts it
reaches over SSH. You diagnose; you never fix.

- You run read-only commands only (`df`, `free`, `systemctl status`, `journalctl`,
  `docker ps`, `smartctl -H`, ...). Anything that writes is denied, and so are `Write` and
  `Edit`. On a remote host, read as its read-only user: `list_hosts` gives the exact `ssh`
  prefix for each host.
- When a ticket wakes you, read it, investigate, and record what you found and what you
  propose with `write_diagnosis` on that ticket.
- When a fix needs a command on a machine, ask for it with `request_fix`: the exact command,
  the host, the reason and the ticket. The owner approves it with a strong confirmation and
  the engine runs it. You never run it yourself.
- Rules are data: `list_rules` shows them; `add_rule` and `tune_rule` change them, always
  with a reason a reader understands a year from now. Prefer tuning a noisy rule to adding
  another one. You cannot disable a rule; the owner can.
- On the daily report, be short: what is healthy, what is not, open tickets, rules you
  changed and why.
- {STATUS_RULE}
- {ASK_RULE}
"""

# Plan §5, rule 2: agents that touch machines run read-only commands only.
IT_CONFIG = {PERMISSION_MODE_KEY: READ_ONLY_MODE}

# The tools every generic department member holds on top of the role's task tools.
GENERIC_TOOLS = frozenset({"write_document", "request_outward_action"})

GENERIC_FOCUS = {
    "general": "You do whatever the department's tasks ask, carefully and briefly.",
    "research": "You find, check and summarise facts. Name the source of every claim.",
    "marketing": "You plan and draft campaigns and copy. Publishing is the owner's decision.",
    "finance": "You keep the numbers: budgets, costs, forecasts. Paying anyone is the owner's.",
    "content": "You write and edit articles, posts and documentation for a named audience.",
    "admin": "You handle paperwork, scheduling and records. Writing to outsiders is the owner's.",
}

default_kinds.register(
    IT,
    DepartmentKind(
        IT,
        IT_INSTRUCTION,
        deliverables=frozenset({REPORT, DECISION}),
        head_role=IT,
        head_config=IT_CONFIG,
    ),
)
for _key, _focus in GENERIC_FOCUS.items():
    default_kinds.register(_key, DepartmentKind(_key, _focus, default_tools=GENERIC_TOOLS))
