# Security policy

labhq runs AI agents on your own machines, in your own repositories, with your own
permissions. This page says which versions get fixes, how to report a vulnerability and
which behaviour counts as one.

## Supported versions

Until 1.0, only the latest pre-release receives security fixes. Upgrade to it before you
report, and say which version you ran (`labhq --version`).

| Version | Supported |
|---|---|
| Latest pre-release (for example `0.5.0b1`, tag `v0.5.0-beta.1`) | Yes |
| Any earlier release | No |

## Reporting a vulnerability

Report privately through GitHub private vulnerability reporting:
[open a draft advisory](https://github.com/kostaslamas/labhq/security/advisories/new)
(the repository's **Security** tab, then **Report a vulnerability**). Do not open a public
issue, pull request or discussion for a vulnerability.

Include the version, the platform, the steps or a proof of concept, and what an attacker
gains. Never include a real credential or token in a report; a redacted placeholder is
enough.

labhq is maintained by one person in spare time. Expect an acknowledgement within a week.
A fix ships in the next pre-release, and the advisory is published with it, crediting you
unless you ask otherwise.

## Credentials

labhq never handles Claude credentials ([ADR 0001](docs/adr/0001-billing-subscription-or-api-key.md)).
It does not read, copy, store or log Claude login files or tokens, and it does not call
undocumented endpoints. Agents use the Claude Code login that already exists on the
machine, or `ANTHROPIC_API_KEY` when you set it; that key is the only credential labhq
passes to a child process. A CI guard fails the build when application code references a
credential file or a token variable. Any path by which labhq exposes, copies or logs a
credential is in scope.

## In scope

- **The push guard.** Agents must not push or merge on their own
  ([plan §5](planning/plan.md#5-εγκρίσεις-και-ασφάλεια), rule 5): a PreToolUse hook that
  parses the command, a disabled push URL in each worktree, and no git credential in the
  worker's environment. A command that a worker in its worktree can run to publish
  commits without an approval is a vulnerability
  ([manual check](docs/checks/push-guard.md)).
- **The credential-free worker environment.** A worker process that receives a credential
  other than `ANTHROPIC_API_KEY`, or a git or forge token.
- **MCP authentication.** A request that reaches a Call Center tool without a valid bearer
  token, or a token that leaks through logs, errors or responses.
- **Approvals and their risk classes.** A heavy action (push, merge, deletion, budget
  overrun, machine intervention) that runs without its approval, an approval issued from a
  voice client, an approval that executes something other than what was approved, or an
  approval missing from the audit record.
- **Exposure.** Making the server reachable from the internet: a public endpoint that
  serves anything without authentication, or a tunnel that exposes more than the MCP
  endpoint it was set up for.

## Out of scope

- **Your own agents acting inside your own permissions.** By default agents run with
  `bypassPermissions`, so an agent can do anything the user running the server can do
  ([plan §5](planning/plan.md#5-εγκρίσεις-και-ασφάλεια), rule 6). Real isolation needs the
  optional sandbox or a separate OS user. An agent that deletes files, reads your SSH key
  or pushes from your main checkout with your own credentials, outside the worktree layers
  above, is the documented trust model, not a vulnerability.
- Prompt injection that makes an agent misbehave within those same permissions.
- Vulnerabilities in Claude Code, the Agent SDK, `git` or other third-party software,
  which belong to their maintainers. Report them there; tell us if labhq should work
  around one.
- Spending through a model provider that stays within a budget you configured.
- Anything under `spikes/`, which holds throwaway prototypes that do not ship.
