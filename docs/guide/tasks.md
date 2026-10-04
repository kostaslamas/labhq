# Tasks and reviews

Tell the CEO which project owns an objective. The Call Center delivers your words to the
CEO; the CEO uses `delegate_task` to give the objective to that project's active manager.
The voice `order` tool also sends a task to the active manager when you do not name an
assignee. A project needs an active manager for that route.

Managers and leads split their assigned task with `create_task`. A child created during a
task run is linked to that task automatically; they can also name its parent explicitly.
Assign each child to a team member to wake them in their own worktree. A worker reports a
result or blocker with `report_task`. The parent task's assignee wakes to inspect it and either accepts the child
or sends it back with feedback. The same review applies at every level.

A manager reports the root objective to the CEO only after its children are resolved. The
CEO reviews and can return it to the manager. A favorable CEO review sends you a
notification and leaves the root task open for your final decision:

```sh
labhq task pending
labhq task accept 12 --feedback "The result meets the objective"
labhq task return 12 --feedback "The mobile flow still fails"
```

Returning a task wakes its manager with your feedback. Only your `task accept` closes the
root task. Merge and push remain separate heavy actions that need their own approval.

If an assigned agent ends a turn without handing off or reporting a blocker, the scheduler
gives it another turn. After `LABHQ_SCHEDULER_MAX_UNREPORTED_RUNS` turns (three by default),
the task is marked blocked and sent to its reviewer. A reviewer that repeatedly ends a turn
without deciding triggers an owner notification. Budget and agent approvals can still pause
work; the task stays visible instead of being called done.
