# Check: persistent CEO tmux sessions

The CEO uses the private tmux socket configured by `LABHQ_TMUX_SOCKET` (default
`labhq`). A Claude Code turn creates `ceo_claude`; a Codex turn creates
`ceo_codex`. The backup kind gets its own conversation.

1. Send the CEO two messages from the UI. `tmux -L labhq list-sessions` should show
   one `ceo_<kind>` session. `tmux -L labhq capture-pane -p -t =ceo_<kind>:` shows
   both turns in the same pane. The database runs have the same `session_id_after`.
2. Switch the CEO to its backup kind and send another message. Its separate
   `ceo_<kind>` session should appear; switching back reuses the original pane.
3. After a completed turn, attach and quit the CLI. tmux keeps the dead pane.
   Send a new message. labhq should respawn the CLI in the same named session
   and resume the stored conversation ID.
4. Ask the CEO for its projects and agent sessions. It should use `list_projects`
   and `list_agent_sessions`, and can read its operational skill from
   `.labhq/skills/ceo-operations/SKILL.md` in its agent home.

The automated fake CLI test covers reuse, fallback, quit and resume without
calling a model. A preexisting `ceo_*` session without labhq's marker is left
untouched, to avoid driving a person's terminal.
