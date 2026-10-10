# 0012. A CEO tab for the CEO's settings, not for chat

## Status

Accepted (2026-10-10). Amends ADR 0011: the sidebar may have a CEO entry, as long as it holds
no chat.

## Date

2026-10-10

## Context

ADR 0011 removed the CEO chat page and its `/ceo` route so that chat lives in one place, the
Call Center widget. The CEO's own settings stayed on the Projects page: the main and backup
agent, and the folders the session scan looks in. The owner finds that wrong. The CEO serves
every project, so what it is and where it looks do not belong to any one project.

## Decision

- **A `/ceo` tab** holds the CEO's assignment and the scan folders ("Where labhq looks for
  sessions"). The Projects page keeps the project list and the add form.
- **Still no chat.** `freeText.spec.ts` keeps failing on a `ceo-chat` route and on a text input
  outside the widget that is not listed. Only the `/ceo` path and `ceo.nav` are now allowed.
- **Links follow.** Notifications and the MCP scan-scope tool point at `/ceo?panel=scan`. An old
  `/projects?panel=scan` link redirects there. A found folder's "Add project" button opens
  `/projects?add=<folder>&name=<name>`.

## Consequences

- The sidebar has six entries.
- Folders stay global: one list for the CEO, never per project.
