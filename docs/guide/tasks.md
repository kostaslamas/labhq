# Tasks and reviews

Tell the CEO which project owns an objective. The Call Center delivers your words to the
CEO; the CEO uses `delegate_task` to give the objective to that project's active manager.
The voice `order` tool sends your words to the CEO the same way. A project needs an active
manager for the CEO to delegate to.

In the CEO tab, choose the CEO's main and backup agent. One CEO serves every project.
Project managers added from the UI report to that CEO automatically.
For a project without a manager, **Assign a saved agent session** lists the sessions of the
chosen Claude Code, Codex, Gemini or Aider CLI in that project's exact folder. The list
includes sessions whose CLI has quit. Choose the session ID and approve the request; labhq
resumes that conversation as the project's manager. A running CLI in the folder must first
use **Use a running tmux agent as manager**, so two processes never drive the same session.
The session list shows IDs and update times, without conversation text.
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
CEO reviews and can return it to the manager. A favorable CEO review becomes a CEO report:
it appears in the CEO chat and on Today, notifies you, and leaves the root task open for
your final decision. Accept or return it with the buttons on the report, or tell the CEO in
the chat; the CEO can record your decision only by quoting your own words. The CLI does the
same:

```sh
labhq task pending
labhq task accept 12 --feedback "The result meets the objective"
labhq task return 12 --feedback "The mobile flow still fails"
```

Returning a task wakes its manager with your feedback. Only your decision closes the
root task. Merge and push remain separate heavy actions that need their own approval.

If an assigned agent ends a turn without handing off or reporting a blocker, the scheduler
gives it another turn (turn this off with `LABHQ_SCHEDULER_AUTO_NEXT_TURN=false`). So that a
stuck task is never invisible, every `LABHQ_SCHEDULER_STALL_ALERT_RUNS` silent turns (three by
default) wake its reviewer, the parent task's assignee, who can look at it with
`task_overview` and give feedback, split or reassign it, or ask you; the task keeps going
meanwhile.

After `LABHQ_SCHEDULER_MAX_UNREPORTED_RUNS` silent turns (five by default) the agent stops: the
task is marked blocked and sent to its reviewer, and a reviewer that keeps ending turns
without deciding triggers an owner notification. Set it to 0 to let an agent keep going until
its budget or the plan-usage cap stops it. Budget and agent approvals can still pause
work; the task stays visible instead of being called done.

## The CEO acts on its own

The global CEO does not wait to be asked. `LABHQ_CEO_HEARTBEAT_SECONDS` (3600; 0 turns it off)
wakes it once per period with a short brief of only what changed since its last turn: new
reports, stalled tasks, new approvals and budget warnings. When you approve or reject
something the CEO or a manager requested, that agent is woken once with the decision. Meetings
on a cadence (`LABHQ_MEETINGS_CADENCE_SECONDS`) are requested and, once you approve them,
started by the running program.

`LABHQ_AUTONOMY=paused` (or `PUT /api/autonomy`) stops all of that: no timer, heartbeat or
automatic next turn starts, and held wakeups wait until you turn autonomy `on` again. Your own
messages to the CEO still get through. The switch you set at runtime wins over the
environment variable.
