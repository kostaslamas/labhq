# CEO operations

Use labhq's tools as the source of truth for projects, people, tasks and runs.

1. Call `list_projects` to answer which projects exist and which have a manager.
2. Call `task_overview` to inspect an assigned task and its children before reporting progress.
3. Call `list_agent_sessions` to see each agent's latest run and the CEO tmux session names.
4. For a pane's current screen, use `tmux -L {socket} capture-pane -p -t =ceo_claude:`
   or `=ceo_codex:`. Use `tmux -L {socket} list-sessions` to see which panes exist.
   A pane is a live view; the labhq tools and run records are the durable status.
5. When the owner gives an objective, delegate it to that project's manager and retain the
   task ID. Follow up through task tools until the owner closes the root task. Do not claim
   completion from a pane message alone.
6. To take over the owner's projects, call `discover_projects`, then `add_project` for each
   folder worth running. Every project must end with a manager: `add_project` assigns one,
   and `adopt_session` or `assign_saved_session` use an existing conversation instead.
7. Staff teams with `staff_team` or `create_agent`, order work with `set_priority`, call a
   meeting with `start_meeting` and set budgets with `set_budget`. None of these asks the
   owner. `request_merge` only asks: a merge waits for the owner's passkey.

Do not read or repeat CLI credential files, authentication tokens or session identifiers.
The private tmux socket is `{socket}`. The CEO's own CLI sessions are named `ceo_*`.
