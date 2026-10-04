# Security

labhq starts AI agents on your machine, in your repositories, with your permissions. This
page says what it protects, what it does not, and how to set it up so that a mistake by an
agent stays small. To report a vulnerability, follow [SECURITY.md](../../SECURITY.md); never
open a public issue for one.

## What an agent can reach

By default every agent runs in `bypassPermissions` (Claude Code's
`--dangerously-skip-permissions`) inside its own git worktree, so it works without stopping
to ask for each command. The worktree is where it is expected to work, not a boundary:

- An agent can read and change any file the user running labhq can, inside the worktree and
  outside it.
- It can run any program that user can run, and reach any network that user can reach.
- Text it reads (a web page, a log, another agent's screen) can carry instructions, and a
  model can follow them.

The IT/Infra department's agents are the exception: they run in read-only mode, where only
allowlisted read commands pass and every other command or file edit is denied. Fixes to a
machine reach it only as a ticket you approve.

## The push guard, and what it does not guarantee

Agents never publish on their own: pushing and merging are heavy actions the engine executes
after your approval. Three layers keep an agent in a worktree from doing it itself:

1. **A parsed-command hook.** A `PreToolUse` hook parses each shell command (not a text search,
   which `git -c x=y push` would slip past) and refuses `git push`, `gh pr merge` and their
   relatives. The hook holds under `bypassPermissions`; this was measured, not assumed.
2. **A disabled push URL.** The worktree's push URL points at a path that does not exist.
3. **No credentials in the environment.** The agent starts without forge tokens, without
   `SSH_AUTH_SOCK`, without askpass helpers, and with every git credential helper reset.

These layers stop the ordinary ways to publish. They do not guarantee that nothing is ever
published:

- A script the agent writes and runs is not parsed by the hook.
- An SSH key on disk without a passphrase works without the agent socket, for example through
  `ssh -i`.
- Another tool on the machine may hold its own credentials.

### Adopted agents

An agent labhq adopted while it was already running (ADR 0005) keeps working in your own
checkout, not a worktree, and as your user. Its push is disabled through `GIT_CONFIG_COUNT`
entries in its environment plus the hook where its CLI has one. That deters, it does not
prevent: `env -u GIT_CONFIG_COUNT git push` restores the repository's own push URL. For an
adopted agent, a sandbox or a separate OS user is the only real barrier.

## Recommended setup: a sandbox or a separate OS user

Only an operating system boundary takes your keys, your agent socket and your credential
helpers out of an agent's reach. Pick one:

- **Docker.** `docker compose up` runs labhq as a non-root user in a container that sees only
  the repositories you mount and its own volumes. See [Containers](containers.md).
- **A separate OS user.** Create a user for labhq with its own home, give it only the
  repositories it works on, and no SSH keys or forge tokens. This suits agents labhq starts
  itself.
- **A sandbox** such as bubblewrap on Linux, which can keep a checkout and a conversation
  store writable while hiding `~/.ssh`, the agent socket and credential helpers. This suits
  adopted agents best, since they must continue a conversation stored under your home.

labhq does not ship a sandbox of its own yet. Until you set one of these up, treat every agent
as you would a script you run as yourself.

## Approvals

Every action is either light or heavy (plan §5):

| Class | Examples | What confirms it |
|---|---|---|
| Light | Starting a meeting, assigning a task, changing a priority, interrupting an agent | Voice or a tap |
| Heavy | Merge into `main`, push, deleting a branch or project, creating a team, exceeding a budget, a change to a machine (restart, cleanup, updates, reboot) | A strong confirmation |

- Agents only request heavy actions. The engine executes them, and only after approval.
- A voice client can never approve a heavy action, not even when an agent asks it to. The
  Call Center's `decide` tool leaves a heavy approval pending and tells you how to confirm it.
- Strong confirmation is a passkey: the notification for a heavy approval opens an approval
  page on your phone that asks for your biometrics. A signed-in session is not enough; the
  server accepts the decision only with a fresh passkey assertion for that one approval. See
  [Passkeys](passkeys.md). At the command line, `labhq approvals approve <id>` still decides
  for whoever holds the machine.
- New agents wait for your approval before they run (`LABHQ_APPROVE_NEW_AGENTS`, on by
  default).
- Every decision is recorded with its payload, risk class, who decided and when.

## The Call Center connector and its exposure

- The MCP endpoint answers only with its token: either `Authorization: Bearer <token>` or the
  token as the last part of the path (`/mcp/<token>`), compared in constant time. Anything
  else gets `401`. `labhq mcp token --rotate` replaces the token, and every connector that
  used the old one stops working.
- The token is stored in the data directory with mode `0600`. Treat the connector URL like a
  password: whoever has it can read your projects' status and request actions. It can still
  never approve a heavy one.
- labhq binds to `127.0.0.1`. Nothing is public until you choose an exposure: the quick tunnel
  onboarding opens, Tailscale Funnel, or your own domain. See [Exposure](exposure.md).
- The server keeps no access log of the connector path, so the token does not land in logs.
- The Call Center passes to an agent only your own words from the current call, never text a
  model composed, and records every delivery.

## Billing

labhq starts the unmodified Claude Code binary and never handles your login (ADR 0001).

- **Your Claude subscription login is the default.** Log in once with `claude` through
  Anthropic's own flow and the agents use that login. You are responsible for staying within
  your plan's terms: Anthropic's
  [legal and compliance page](https://code.claude.com/docs/en/legal-and-compliance) says Pro
  and Max usage limits assume ordinary, individual use of Claude Code and the Agent SDK, and
  the [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview) asks developers
  who build products on the SDK to use API keys. Several agents on schedules may go beyond
  what your plan assumes; budgets, a concurrency of one per agent by default and plan-usage
  thresholds (`LABHQ_PLAN_USAGE_WARN_PERCENT`, `LABHQ_PLAN_USAGE_STOP_PERCENT`) keep them
  closer to it.
- **An Anthropic API key is the alternative.** Set `ANTHROPIC_API_KEY` and Claude Code uses
  API billing. It is the only credential variable labhq passes to a child process, and only
  when you set it.

## Claude credentials

labhq never reads, copies, stores, logs or forwards Claude credentials or session tokens, and
its code never refers to the files they live in. To learn whether you are logged in it asks
the binary (`claude auth status`). A CI guard fails the build if the code references
credential files or token variables other than `ANTHROPIC_API_KEY`.

## Other secrets

Bot tokens for Telegram, Discord and Slack are yours to keep in your shell, a `.env` file
outside the repository or a secrets manager. labhq keeps them out of its logs, its database
and its error messages. The connector token and the Discord settings that onboarding learns
live in the data directory, readable by its owner only; back that directory up as you would
a password store.
