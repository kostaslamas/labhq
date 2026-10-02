# 0001. Run agents on an Anthropic API key or on a Claude subscription login

## Status

Accepted (2026-10-02).

## Date

2026-10-02

## Context

labhq is an open-source (MIT), self-hosted project orchestrator for individuals,
hobbyists and solo developers. Each user runs it on their own machine. It starts
several headless Claude Code agents through the Claude Agent SDK, on schedules
and on events.

labhq code never reads, stores or forwards credentials. The Agent SDK runs the
Claude Code binary, which uses its own login (an `ANTHROPIC_API_KEY`, or the
OAuth login the user already did with `claude`). labhq only starts that process.

What Anthropic's documentation says (fetched 2026-10-02):

Legal and compliance, "Usage policy", https://code.claude.com/docs/en/legal-and-compliance

> Advertised usage limits for Pro and Max plans assume ordinary, individual usage of Claude Code and the Agent SDK.

> **Developers** building products or services that interact with Claude's capabilities, including those using the Agent SDK, should use API key authentication through Claude Console or a supported cloud provider. Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users. Moreover, developers may not collect, store, or intermediate Claude.ai credentials or session tokens — sign-in to a Claude account must complete through Anthropic's own flow.

> Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription, including where a platform hosts Claude Code as described under *Can customers offer Claude Code in their products?* above.

Agent SDK overview, https://code.claude.com/docs/en/agent-sdk/overview

> Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK. Use the API key authentication methods described in the Quickstart instead.

Reading: a developer must not offer claude.ai login or subscription rate limits
as part of a product, and must not touch subscription credentials. A person
using their own subscription with the unmodified Claude Code binary is
explicitly not prevented. The open question is whether a self-hosted orchestrator
that starts many scheduled agents counts as "ordinary, individual usage" and
whether it counts as "a product" offering subscription limits. The pages do not
answer that. We have not asked Anthropic.

## Options considered

### 1. API key only

labhq documents and supports only `ANTHROPIC_API_KEY` (or a supported cloud provider).

- Pros: matches the guidance quoted above exactly. Billing is per use and
  predictable to attribute. No dependence on subscription limits that assume
  interactive use.
- Cons: every user pays per token on top of any subscription they already have.
  A hobbyist with a Max plan sees a higher barrier to try the tool. Scheduled
  agents can produce a surprising bill without a budget cap.
- Risk: low on terms. Medium on adoption.

### 2. Subscription only

labhq tells users to sign in with their Pro/Max account and runs all agents on it.

- Pros: no extra cost for users who already pay for a plan.
- Cons: the docs say developers building products with the Agent SDK should use
  API keys. Several unattended agents on schedules go beyond the "ordinary,
  individual usage" the plan limits assume, so users may hit limits or be
  throttled. Users depend on limits Anthropic can change.
- Risk: high. A project that recommends subscription use as its main path may be
  read as offering claude.ai login or rate limits in a product, and Anthropic
  "may take measures ... without prior notice". The users carry the account risk.

### 3. API key as the documented default, subscription login as an explicit opt-in (recommended)

The documented, default path is an API key. A user who already has Claude Code
signed in on their own machine can choose to let agents use that existing login.

- labhq never handles the login: no OAuth flow, no token read, copy or store,
  no reading of credential files, no proxying. It starts the unmodified Claude
  Code binary, which uses whatever login the user already completed through
  Anthropic's own flow.
- Opt-in is explicit, per installation, and shows a notice that links to
  Anthropic's Consumer Terms of Service and to the legal-and-compliance page,
  and says that the user is responsible for staying within their plan's terms.
- Pros: the safe path is the default. Users with a plan can still try the tool
  on their own machine, which the docs do not prevent. No credential code to
  secure or audit.
- Cons: two code paths to document and test. The notice adds a step. It does not
  remove the open question above about scheduled multi-agent use.
- Risk: low to medium. The remaining risk is Anthropic reading "ordinary,
  individual usage" more narrowly than we do. Mitigation: the notice, no
  recommendation of subscription use in marketing, and a written question to
  Anthropic (sales contact is named on the page) before a 1.0 release.

## Decision

The user's existing Claude Code login (their subscription) is the default.
An Anthropic API key is the alternative: labhq uses API billing automatically
when `ANTHROPIC_API_KEY` is set in the environment. Onboarding shows a one-time
notice that links to Anthropic's Consumer Terms of Service and to the
legal-and-compliance page, and says that the user is responsible for staying
within their plan's terms. labhq never handles credentials: it only starts the
unmodified Claude Code binary, which uses whatever login the user completed
through Anthropic's own flow.

This differs from the earlier recommendation (option 3, API key as the
default). The owner chose it for two reasons: people who already pay for a plan
incur no extra cost, and the documentation explicitly allows an end user to
sign in to the unmodified Claude Code binary with their own subscription.

## Original recommendation

Option 3. This was a recommendation, written before the owner decided.

## Consequences

- Onboarding uses the existing Claude Code login by default and shows the notice once; setting `ANTHROPIC_API_KEY` switches to API billing.
- labhq checks only that the `claude` binary reports a logged-in state through
  its documented interface.
- The README and docs explain both paths, state that the subscription login is
  the default and that an API key is the alternative, and link to the quoted pages. They do not describe
  subscription use as a way to avoid API costs.
- Risk mitigations: low default concurrency, so scheduled agents stay close to
  "ordinary, individual usage", and a written question to Anthropic before 1.0.
- Agent configuration offers a per-run budget and turn limit so scheduled
  agents cannot run up cost or exhaust plan limits unnoticed.
- The usage dashboard reads limits and usage only from official sources, such as
  the `rate_limits` JSON that Claude Code passes to the statusline command, and
  from the Agent SDK's own result messages. It never reads credential files,
  never calls undocumented endpoints, and never uses an OAuth token itself.
- A CI guard fails the build if the code references Claude credential file
  paths or token environment variables other than `ANTHROPIC_API_KEY`
  passed through to the child process.
- Re-open this ADR if Anthropic changes the quoted pages or answers the
  open question.
