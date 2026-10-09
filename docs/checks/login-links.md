# Manual check: a tool's login link reaches your phone and the Call Center

CI proves the flow against fakes (`tests/logins/`, `tests/channels/`): a fake status command, a
fake pane that prints a link, and a mock notifier. Only the real tools can prove their own
commands and screens, so this is a manual check. Tests never do it (CONTRIBUTING.md §7).

## What it proves

For each tool you use, when it is logged out:

1. labhq starts the tool's own login command in a private tmux pane and finds its link.
2. The link reaches every enabled channel once, and the CEO reports it in the Call Center.
3. After you finish in a browser, the next check passes and the CEO confirms.
4. labhq never read a credential file, never relayed a code, and the tool stored its own login.

## The commands to confirm

The registry (`src/labhq/logins/tools.py`) records each tool's status command, login command
and the hosts its link may point at. Re-check them against the tool's own help when you run
this, and update the registry if a tool renamed a subcommand:

| Tool | Status | Login |
|---|---|---|
| Claude Code | `claude auth status --json` | `claude auth login` |
| Codex | `codex login status` | `codex login` |
| Gemini CLI | none (its sign-in dialog) | `gemini` |
| Aider | none | none (provider API key) |
| OpenCode | `opencode auth list` | `opencode auth login` |
| Cursor CLI | `cursor-agent status` | `cursor-agent login` |

The sign-in dialog wording of Codex and Gemini CLI in `src/labhq/adapters/tmux/agents.py` was
not checked on a machine. Confirm each pattern matches the real dialog, and fix it if not.

## Run it

1. Set up at least one channel: `labhq channels add ntfy --name phone --field topic=<topic>`
   (or the Channels page). Its test message must arrive.
2. Log the tool out with its own command (for example `codex logout`).
3. In `labhq serve`, or with a Python shell, ask for the login:

   ```sh
   uv run python - <<'PY'
   import asyncio
   from labhq.cli.context import execute
   from labhq.logins.program import default_login_service

   async def main(context):
       service = default_login_service(context)
       outcome = await service.ensure("codex")
       print(outcome.created, outcome.request and outcome.request.id)

   execute(main)
   PY
   ```

4. Confirm the message "Το Codex θέλει login: <link>" arrived on the phone, once, and that the
   Call Center (`reports`) says the same.
5. Open the link and log in. If the tool asks for a code, paste it in the terminal
   (`tmux -L labhq attach -t <pane>`, the pane name is in the message). labhq must not have
   offered to relay it.
6. Within the status interval, the phone and the Call Center get the confirmation, and the
   pane is gone (`tmux -L labhq ls`).

## Record the result

Write the date, the tool versions and what differed in the pull request that changes the
registry. A tool whose link never appears is reported as such: the owner gets the command to
run, which is the designed fallback.
