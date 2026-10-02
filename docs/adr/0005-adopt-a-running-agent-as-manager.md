# 0005. Adopt an agent that already runs a project, as its manager

## Status

Accepted (2026-10-03).

## Date

2026-10-03

## Context

Most owners will bring projects that an agent already works on: a `claude`, `codex`,
`gemini` or `aider` process in their own terminal or tmux, in the project's main checkout,
with a conversation that holds the project's context. The CEO must be able to take such an
agent over and continue its work without losing that conversation.

Three facts constrain how:

- A process cannot move from the owner's tmux server into labhq's private one (ADR 0003).
  Continuing means ending the original process and resuming its conversation elsewhere.
- Two processes must never drive the same session at once (plan §4.1).
- Sessions are stored per working directory, so the resumed agent must run in the same
  directory: the owner's main checkout, not a labhq worktree. The worktree's disabled push
  URL therefore does not apply. On an SSH remote, a key file without a passphrase works even
  without `SSH_AUTH_SOCK`.

labhq never reads credential or session files (ADR 0001).

## Decision

### The adopted agent becomes the project's manager

It holds the project's context, so it is the natural manager. It joins the hierarchy under
the CEO; the project row is created if it does not exist.

### Resume by directory, not by id

Each agent registry entry (ADR 0003) gains a `continue` template: the CLI's own way to
continue the most recent conversation in the current directory (for Claude Code,
`claude --continue`; the others are verified when this is built). labhq never has to
discover the old session id; it records the id from the resumed run on, as for any run.

### Adoption flow

1. Request: the owner names the agent to adopt, or the CEO lists running agents (known CLI
   processes and their working directories) and proposes one.
2. Observe: until the move, labhq only captures the agent's screen. The Call Center can
   already answer about it (ADR 0004). labhq sends it no keys.
3. Move: when its turn ends, the original process ends, then labhq starts the agent's
   `continue` template in the same directory on the private tmux server.
4. Record: the agent, its role (manager) and its session are stored.

Adoption ends a process the owner started, so it needs the owner's confirmation. It is a
light action: the conversation is kept.

### Push stays disabled without touching the owner's repository

The adopted manager's environment disables pushing through `GIT_CONFIG_COUNT` entries
(each remote's push URL and an empty `pushInsteadOf` prefix pointing at the disabled URL),
on top of `worker_environment`. The settings apply to the agent's processes only; the
repository's own config is unchanged. With the parsed-command hook where the CLI supports
it, the adopted agent again has two layers.

### The manager learns the rules; the engine does not trust it to

The rules for a labhq manager:

- Keep `.labhq/status.md` up to date every turn (ADR 0004).
- No more code edits in the main checkout: split work into tasks for workers, who work in
  their own worktrees.
- Never push or merge: request an approval.
- Terse to agents, natural to the owner (plan §7.1).
- Ask the owner through `questions`, not by waiting at the terminal.

They reach the agent in three ways, chosen per agent entry (`rules_injection`):

1. Appended to the system prompt on every start, where the CLI allows it alongside
   `continue` (to verify for each CLI). This survives compaction.
2. Otherwise sent as the first message after the move, and again after every compaction or
   new session.
3. Always written to `.labhq/rules.md`, listed in `.git/info/exclude` so it never reaches a
   commit. The owner's `CLAUDE.md` and other tracked files are never changed.

The engine checks, it does not trust: a turn without a status update gets a request to
update; a change in the main checkout after the move notifies the owner; push and merge
fail regardless.

### Uncommitted work stays where it is

Changes the agent left uncommitted at the move belong to the owner's checkout. labhq does
not touch them. It records them in the status, and the owner decides whether they become
the first task.

## Consequences

- The agent registry of ADR 0003 gains `continue` and `rules_injection`.
- `labhq.worktrees` gains an environment variant for agents outside a worktree, disabling
  push through `GIT_CONFIG_COUNT`.
- Discovery reads process lists and working directories only, never session stores.
- Adoption lands after the tmux adapter (#25), as its own issue.
- Until the move completes, the original process keeps the owner's full environment and
  labhq's guarantees do not apply to it.
