# 0007. Approval notifications: Web Push from the labhq web app, external gates as plugins

## Status

Accepted (2026-10-03).

## Date

2026-10-03

## Context

Plan §3.2 rule 6 and §9.1 made ntfy the default notifier, with Telegram optional, and #32
built both. A heavy approval then reaches the phone through a third-party app, and the
owner must switch to the labhq web app to confirm it with a passkey (#62, #67).

A web app installed on the phone's home screen can receive Web Push directly: the server
signs each push with its own VAPID key, and no account, store or third-party service sits
in between. iOS allows Web Push only for a web app added to the Home Screen (iOS 16.4 and
later); a plain browser tab cannot subscribe. Tapping the notification opens the same app,
where the passkey that confirms the approval already lives.

Some owners already run an approval gate of their own: a self-hosted page that sends its
own push, shows what is being approved and accepts it with a biometric passkey. Plan §5
already says such gates plug in; nothing implements that yet.

## Decision

### Web Push from the labhq web app is the default notifier

- The web app (Phase 4) is installable: a manifest and a service worker.
- `webpush` is a new registration in the notifier registry and the default kind. The VAPID
  key pair is generated once and kept in the data directory with mode 0600.
- Subscribing needs a signed-in passkey session, because a subscriber receives the text of
  every approval. A subscription that the push service reports gone (404 or 410) is pruned.
- An approval notification opens `/approve/<id>` in the installed app (#67).
- ntfy and Telegram stay as registrations for owners who want them. Onboarding no longer
  sets up ntfy by default.

### External approval gates are plugins

- `labhq.approvals.gates`: a registry of gate adapters. The first is a generic HTTP gate:
  labhq posts the approval as a request, polls its status, and resolves the labhq approval
  from the answer. Its URL, token and paths are settings; nothing about a particular gate
  is in the code.
- A gate answer resolves a heavy approval only when the gate reports a passkey proof. An
  answer approved by any weaker proof (for example a password) leaves the approval pending
  and is recorded. A denial rejects it; an expiry leaves it pending.
- A gate approval is recorded with confirmation kind `external_gate` and the gate's name as
  the decider. The token is never logged or stored in a row.
- With a gate configured, heavy approvals go to the gate; light approvals keep their tap.

## Consequences

- Plan §3.2 rule 6 and §9.1 change: Web Push from the installed web app is the default,
  ntfy and Telegram are options, and an external gate can take over heavy approvals.
- Phase 4 gains two issues: Web Push from the web app, and the HTTP gate adapter.
- Onboarding's check that a test notification arrives uses Web Push once the web app is
  installed on the phone; before that it shows the install step.
- The Phase 2 criterion "the notifier sends a message when an approval is created" holds
  for every registered notifier, Web Push included.
