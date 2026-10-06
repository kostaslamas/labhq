"""Rules several role instructions repeat, kept once."""

STATUS_RULE = (
    "Keep the task's status file up to date every turn: `summary`, `done`, `next`, "
    "`blockers`, `refs` and `questions`. The task brief names the file for plain folders; "
    "otherwise use `.labhq/status.md`. The engine reads it; nobody waits at your terminal."
)
ASK_RULE = (
    "When you need the owner, write the question under `questions` in the status file and "
    "carry on with what does not depend on the answer."
)
NO_PUSH_RULE = (
    "Never push or merge, and never ask a tool to do it for you: the engine refuses it. "
    "Pushes and merges are heavy actions the owner approves and the engine executes."
)
