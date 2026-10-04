# User guide

labhq is a self-hosted project orchestrator: one person, many projects, and a team of AI
agents. Start with the [README](../../README.md) for what it is and how to install it, then
read the pages below as you need them.

## Get started

- [Onboarding](onboarding.md): one command to a working labhq, with no third-party account.
- [Containers](containers.md): run labhq with Docker or rootless Podman.
- [Configuration](configuration.md): every setting and its environment variable.
- [Platforms](platforms.md): Linux, macOS and Windows support, installing `uv` on Windows,
  and the native Windows limitations.

## Use it

- [Call Center](call-center.md): add the connector to Claude or ChatGPT, the tools, and what
  the Call Center will and will not do.
- [Tasks and reviews](tasks.md): delegate objectives, split work, review results and make
  the final decision.
- [Exposure](exposure.md): a public URL for the connector: quick tunnel, Tailscale Funnel or
  your own domain.
- [Passkeys](passkeys.md): sign in to the web UI, approve from your phone, and why a passkey
  belongs to one address.
- [Notifications](notifications.md): ntfy and Telegram.
- [Approval gates](approval-gates.md): hand heavy approvals to a self-hosted gate with a passkey.
- [Discord](discord.md): meetings mirrored to your own Discord server.
- [Slack](slack.md): meetings mirrored to Slack.

## Stay safe

- [Security](security.md): what agents can reach, the push guard, the recommended sandbox or
  separate user, approvals, the connector and billing.

A new page in this directory adds its line here; CI fails when a page is missing from this
index.
