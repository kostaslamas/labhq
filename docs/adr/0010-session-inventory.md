# 0010. Session inventory: a free scan, an analysis only on request

## Status

Accepted (2026-10-09).

## Date

2026-10-09

## Context

The owner has agent sessions in many folders, made with several tools. labhq should know
about all of them, tell the CEO, and let the owner decide which to continue or close. The
tools' subscriptions may differ or be gone, and reading conversations costs money and
privacy.

## Decision

### The scan is free

It reads the process table (ADR 0005's discovery), each tool's local store for ids, folders
and times, git, and `gh` when it is logged in. It never reads conversation text and calls no
model. Store layouts are rows in `labhq.inventory.stores`; a tool in a new format adds a
format reader, never a branch in the scanner. The Cursor stores keep a login in the same
SQLite file as the chats, so their queries name the chat keys and select nothing else.
Layouts checked 2026-10-09 against upstream source where available:

- OpenCode: `opencode.db`, table `session` (`directory`, `time_updated` in ms, `parent_id`,
  `time_archived`). The legacy JSON layout is not read.
- Cursor CLI: `chats/<hash>/<id>/meta.json`. The sibling `store.db` is never opened.
- Cursor IDE: `composer.composerHeaders` in the global database for Cursor 3, and the
  workspace database's `composer.composerData` for older versions, with timestamps taken from
  `composerData:<id>` through `json_extract`. Read-only, so its continue path is a hand-off.

### Login and plan come from the tool, not from files

A kind's `login_status` is the tool's own status command (exit code, and an email address in
its output as the account). A tool without one is reported as unknown, never as logged in.
Plan room is the existing usage readings. No credential file is opened (ADR 0001).

### Analysis needs a per-project request and a confirmed estimate

The owner names one project. labhq records a light `analyse_project` approval holding the
estimate, the kind and the sessions to read; approving it is the confirmation and the
consent to read that project's transcripts. There is no bulk analysis. The runner is chosen
from kinds that are installed, logged in and under their plan cap, cheapest first, and is not
the tool that made the sessions unless the owner allows it. The result is a markdown file in
the data directory and a pointer report to the CEO.

### Closing and continuing reuse existing mechanics

Close is a light `close_session` approval that ends an idle process and re-checks, at
execution, that no turn is running. Continue is the adoption flow (ADR 0005) for running and
saved CLI sessions; a Cursor IDE chat becomes a task for a CLI agent in the same folder with
the latest analysis as context. A parent folder with two or more projects is proposed a folder
manager, created by a light `create_folder_manager` approval.

## Consequences

- A running agent's state is sampled (CPU and child processes, and a dialog match on its
  tmux pane); it is a hint, which is why close checks again.
- A Cursor CLI chat's conversation is an opaque blob store; its analysis sees git and code
  only, and says so.
- Every price in an estimate is a setting, not a quote.
