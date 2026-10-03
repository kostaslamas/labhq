# Manual check: adopt a running `claude` session as a project's manager

CI adopts a fake CLI agent (`tests/adoption/fake_cli.py`) from a real tmux server into
labhq's private one, with every step of the move and the engine checks under test. Only a
real Claude Code session can prove that `claude --continue` picks up the conversation of the
original process, so this is a manual check, run on a developer machine. Tests never do this
(CONTRIBUTING.md §7). See ADR 0005.

## What it proves

| Step | Passes when |
|---|---|
| Discovery | `labhq adopt discover` lists the `claude` process and its working directory |
| Request | `labhq adopt request <pid>` creates a pending `adopt_agent` approval and warns when no sandbox is configured; the session keeps running untouched |
| Move | After `labhq approvals approve <id>`, the original `claude` exits once its turn has ended, and `tmux -L labhq attach -t adopted-<pid>` shows the same conversation continued, in the same directory |
| Record | `labhq org tree` shows the agent as the project's manager under the CEO; its session id is in `agents.config["adoption"]["session_id"]` after its first turn |
| Rules | `.labhq/rules.md` exists, `git status` does not list it, and the continued agent answers a question about its rules correctly |
| Checks | `labhq adopt check` asks for a status update after a turn that did not write `.labhq/status.md`, and an edit in the checkout produces a `checkout_changed` notification |

## Push is deterred, not prevented

The adopted agent runs as you, in your main checkout. labhq's environment points every
remote's push URL at a path that cannot exist (`GIT_CONFIG_COUNT` entries) and drops your
git credentials, and Claude Code's push guard hook refuses `git push` commands. These layers
deter a push; they do not guarantee that none happens:

- `env -u GIT_CONFIG_COUNT git push` drops the environment entries;
- an SSH key file without a passphrase on disk needs no agent socket;
- a script that runs `git push` is not seen by the hook, and some CLIs have no hook at all.

Only a sandbox or a separate OS user prevents a push (plan §5, rule 6). A separate OS user
cannot continue a conversation stored under your home, so for adoption use a sandbox that
keeps the checkout and `~/.claude` writable while hiding `~/.ssh`, the SSH agent socket and
git credential helpers. labhq puts the words of `LABHQ_ADOPT_SANDBOX` (a JSON list) before
the continued command, for example with bubblewrap:

```sh
export LABHQ_ADOPT_SANDBOX='["bwrap", "--dev-bind", "/", "/", "--tmpfs", "/home/me/.ssh",
  "--unsetenv", "SSH_AUTH_SOCK", "--die-with-parent", "--"]'
```

The adoption confirmation warns when it is empty.

## Before you run it

- tmux 3.x and Claude Code, logged in with its own flow. labhq never reads or handles the
  login (ADR 0001).
- A scratch git repository with a remote you do not mind protecting, and a commit.
- `uv run labhq init` done.

## Run it

1. In your own terminal (not labhq's tmux), in the scratch repository, start `claude` and
   ask it something memorable, for example "Remember the word 'heliotrope'". Leave an
   uncommitted edit in a tracked file.
2. `uv run labhq adopt discover` and note the pid of that `claude`.
3. `uv run labhq adopt request <pid> --project adopt-check`. Note the approval id and the
   warning.
4. `uv run labhq approvals approve <id>`. Outside tmux, labhq waits until the process has used
   no CPU and run no child process for `LABHQ_ADOPT_QUIESCENCE_SECONDS` (default 10).
5. `tmux -L labhq attach -t adopted-<pid>` and ask "Which word did I ask you to remember, and
   what are your rules?". Detach with `C-b d`.
6. `uv run labhq adopt check`, then edit a file in the repository and run it again.
7. Check: the uncommitted edit from step 1 is unchanged; `git status` shows no `.labhq/`;
   `git config --list --local` is as before; inside the attached session, a `git push` asked
   of the agent is refused by the hook, and run by hand from its shell it fails at the
   disabled push URL.

## Record

| Date | Claude Code version | Result | Notes |
|---|---|---|---|
| | | not run yet | |
