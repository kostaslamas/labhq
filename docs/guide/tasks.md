# Tasks and reviews

Tell the CEO which project owns an objective. The Call Center delivers your words to the
CEO; the CEO uses `delegate_task` to give the objective to that project's active manager.
The voice `order` tool also sends a task to the active manager when you do not name an
assignee. A project needs an active manager for that route.

On the Projects page, choose the CEO's main and backup agent. One CEO serves every project.
Project managers added from the UI report to that CEO automatically.
Open CEO in the sidebar to send the CEO a direct message and see its answer. Each message
uses the scheduler, so it waits while the CEO is busy and follows the configured backup.
The backup runs when the main agent's program is unavailable or its plan usage is paused;
the CEO keeps the same identity and reporting lines. Removing the backup leaves the main
agent assigned. Switching agent kinds starts a fresh session while keeping the task's folder.

Managers and leads split their assigned task with `create_task`. A child created during a
task run is linked to that task automatically; they can also name its parent explicitly.
Assign each child to a team member. In Git projects, each task runs in its own worktree; in
projects backed by an ordinary folder, agents edit that folder directly and changes are
visible immediately, without a merge or push approval. Plain-folder tasks keep separate
status files under `.labhq/tasks/<task-id>/status.md`. A worker reports a
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
gives it another turn, and keeps doing so until the task is resolved: the CEO and the
managers do not stop on their own. Only the agent's budget and the plan-usage cap stop it. So that a stuck task is never
invisible, every `LABHQ_SCHEDULER_STALL_ALERT_RUNS` silent turns (three by default) wake its
reviewer, the parent task's assignee, who can look at it with `task_overview` and give
feedback, split or reassign it, or ask you; the task keeps going meanwhile.
Set `LABHQ_SCHEDULER_MAX_UNREPORTED_RUNS` to a positive number to stop after that many
silent turns instead: the task is then marked blocked and sent to its reviewer, and a
reviewer that keeps ending turns without deciding triggers an owner notification. Budget and agent approvals can still pause
work; the task stays visible instead of being called done.
