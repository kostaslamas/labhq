# labhq

An open-source, self-hosted project orchestrator for one person with many projects and a team
of AI agents. A CEO agent oversees all your repositories, each project gets a manager, and
managers run teams of workers. You talk to it by voice from the AI app you already use.

**Status: pre-release.** The engine, the Call Center, the hierarchy, meetings and the IT
department run today. The first release is not on PyPI yet, so the `uvx` and `uv tool`
commands below work from that release on; until then, use Docker or a clone of this
repository. Passkey approvals in the web UI are being finished; until they land, heavy
approvals are decided at the command line.

<!-- Demo GIF slot: uncomment this line when docs/media/demo.gif exists.
![labhq: a call to the Call Center, an approval on the phone, the merge it unblocks](docs/media/demo.gif)
-->

## What labhq is, and is not

labhq is for individuals, hobbyists and solo developers who run more projects than they can
keep in their head. It starts Claude Code agents (and other CLI agents) on your own machine,
in their own git worktrees, on schedules and on events, keeps budgets and asks you before
anything heavy happens.

It is not:

- **A voice product.** labhq has no speech-to-text or text-to-speech of its own. Voice comes
  from the AI app you already use.
- **A platform for companies.** One user, no roles, no organisations, no SSO.
- **The widest agent framework.** It competes on a narrow angle (voice, security, meetings,
  homelab care), not on breadth.

## What makes it different

| | What it means |
|---|---|
| **Call Center** | Add labhq as a connector in Claude or ChatGPT and talk to your CEO by voice. It answers from the database in under two seconds, and reads the agents' screens without interrupting them. No voice code of ours. |
| **Security-first approvals** | Agents ask; the engine acts. Push, merge, deleting and budget overruns need a strong confirmation, never a voice "yes". |
| **Meetings** | Standups, planning and reviews between agents are first-class objects. Their decisions become tasks, mirrored live to your own Discord or Slack if you want. |
| **IT/Infra department** | A built-in department watches your homelab machines, applies its own health rules and opens tickets. Fixes run only after your approval. |

## Install

Linux and macOS, with [uv](https://docs.astral.sh/uv/getting-started/installation/)
installed:

```sh
uvx labhq onboard
```

That one command creates the database, issues the connector token, opens a public URL
through a Cloudflare quick tunnel, prepares notifications and checks the
whole path before it says `labhq is ready.` It needs no account with any third party. See
[Onboarding](docs/guide/onboarding.md).

To keep `labhq` on your `PATH` instead of running it through `uvx`:

```sh
uv tool install labhq
```

With Docker, from a clone of this repository (see [Docker](docs/guide/docker.md)):

```sh
cp .env.example .env     # then set PROJECTS_DIR
docker compose up -d
```

**Windows.** WSL2 and Docker Desktop are the supported ways: inside WSL2 the Linux commands
above apply as they are. Native Windows is best effort: install uv with the PowerShell
installer or `winget` from [uv's installation page](https://docs.astral.sh/uv/getting-started/installation/),
then run the same `uvx` command. On native Windows only the SDK adapter runs (no tmux).

| Platform | Support |
|---|---|
| Linux | Official |
| macOS | Official |
| Windows through WSL2 or Docker Desktop | Official |
| Native Windows | Best effort |

## Quickstart

1. **Onboard.** Run `uvx labhq onboard`. At the end it prints a connector URL with a QR code,
   and the next step for notifications: open the labhq web app on your phone (on iOS, add it to
   the Home Screen first) and enable notifications there.
2. **Add the connector.** In Claude or ChatGPT, add a custom connector and paste the connector
   URL (or scan its QR code on your phone). Leave the authentication fields empty: the secret
   path in the URL is the credential. See [Call Center](docs/guide/call-center.md).
3. **Register your first project.** In another terminal (prefix each command with `uvx` if
   you did not run `uv tool install`):

   ```sh
   labhq project add site --repo ~/code/site --budget-usd 25
   labhq org assign-manager site
   ```

   The manager waits for your approval as every new agent does; `labhq agent approve <id>`
   lets it start.
4. **Give it work.** Ask the Call Center by voice ("what did the teams do tonight?", "tell the
   site team to fix the login form"), or add a task:

   ```sh
   labhq task add --project site --title "Fix the login form" --assignee 2
   ```

   Replace `2` with the manager's agent id from the previous step. A task without an
   assignee stays in the backlog; a voice `order` without an assignee goes to the active
   project manager. The manager can split it into subtasks, and reports the result to the
   CEO for review. You close the root task yourself with `labhq task accept <id> --feedback
   "Accepted"`, or return it with `labhq task return <id> --feedback "What is missing"`.

5. **Approve what is heavy.** When an agent wants to push or merge, a notification reaches
   your phone. Decide with `labhq approvals list` and `labhq approvals approve <id>`.

Every setting is an environment variable; [Configuration](docs/guide/configuration.md) lists
them all. The [user guide](docs/guide/index.md) has the rest.

## Models and billing

labhq starts the unmodified Claude Code binary for its agents and never handles your login.
There are two ways to pay for what the agents use:

- **Your Claude subscription login is the default.** Log in once with `claude` through
  Anthropic's own flow; the agents use that login. Onboarding shows a notice once: you are
  responsible for staying within your plan's terms. Anthropic's
  [legal and compliance page](https://code.claude.com/docs/en/legal-and-compliance) says
  Pro and Max usage limits assume ordinary, individual use of Claude Code and the Agent SDK,
  and the [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview) asks
  developers who build products on the SDK to use API keys. Read both before you choose.
- **An Anthropic API key is the alternative.** Set `ANTHROPIC_API_KEY` in the environment
  and Claude Code uses API billing instead. labhq passes this one variable through to the
  agents and nothing else.

Either way, per-project and per-agent budgets, a low default concurrency and turn limits keep
scheduled agents from running up use unnoticed. The reasoning is in
[ADR 0001](docs/adr/0001-billing-subscription-or-api-key.md).

## Security

labhq runs AI agents with your permissions, so read this before you point it at anything you
care about. The full text is [Security](docs/guide/security.md).

- **Agents can reach what you can reach.** By default agents run in `bypassPermissions` inside
  their own git worktree, so they work without stopping to ask. That is not isolation: an agent
  can read and change anything the user running labhq can.
- **The push guard deters, it is not a wall.** A hook that parses commands refuses `git push`
  and merges, the worktree's push URL is disabled, and the agents' environment carries no git
  credentials. These layers stop the ordinary ways to publish, not a determined escape.
- **The recommended setup is a sandbox or a separate OS user.** Run labhq in Docker, under its
  own OS user or in a sandbox. For an agent you adopted while it was running in your own
  checkout, this is the only real barrier.
- **Heavy actions need you.** Push, merge, deleting, team creation, budget overruns and
  changes to a machine are executed by the engine only after a strong confirmation. A voice
  client can never approve one.
- **The connector is authenticated and exposed on purpose.** The MCP endpoint needs its token,
  the server binds to `127.0.0.1`, and only the exposure you choose makes it public.
- **labhq never handles Claude credentials.** It never reads, copies, stores or logs them.

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Stack

- Backend: Python 3.12, uv, FastAPI, SQLite with Alembic migrations, the Claude Agent SDK.
- Frontend: Vue 3, TypeScript, Pinia, Tailwind 4, shadcn-vue.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md); its rules bind every contributor, human or agent.
The design and roadmap live in [`planning/plan.md`](planning/plan.md) (in Greek), and the
accepted decisions in [`docs/adr/`](docs/adr/).

## License

MIT. See [LICENSE](LICENSE).
