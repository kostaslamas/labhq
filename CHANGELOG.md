# Changelog

Generated from the git history by git-cliff (`uv run python -m tools.changelog`).
Do not edit by hand: CI regenerates this file and fails on any difference.

## v0.1.0-alpha.1

### Features

- add settings, injectable clock and micro-USD conversion (ca7af62)
- **db:** add phase 1 models and the initial migration (44a1d9e)
- **worktrees:** build a credential-free worker environment (95c4609)
- **worktrees:** give each task a worktree and branch with push disabled (7967bfa)
- **guards:** deny publishing commands in a parsed-command Bash hook (4b1aac4)
- **adapters:** add adapter protocol, registry, fake and Claude adapters (b03cd65)
- **runs:** record runs, events, cost and resumable sessions (179c655)
- **approvals:** risk classes as data and engine-executed push (2aacf50)
- **db:** add budget_warnings table for once-per-period warnings (cc5d6e6)
- **budgets:** check agent and project spend against their budgets (fa2e719)
- **economy:** add output style registry per recipient (0f46dd4)
- **economy:** add structured handoff model and terse renderer (b080f78)
- **economy:** add rtk PreToolUse hook for worker shell commands (f372483)
- **health:** sample the local machine into health_samples (bee4c56)
- **health:** add the rule type registry and the threshold type (58c7ffc)
- **health:** open and resolve incidents from rule evaluations (6b40d18)
- **health:** run the collector and rules on the settings interval (fcf77e9)
- **runs:** let start adopt a run the scheduler queued (8881684)
- **scheduler:** add wakeups, dispatch, checkout, timeouts and reaper (e4158f4)
- **cli:** add the command context and operator error reporting (fa22981)
- **cli:** run scheduled tasks in worktrees behind the push guard (cf4e5e6)
- **cli:** add init, project, agent, task, run, approvals and health (1700ead)
- **cli:** add the Phase 1 demo (622114e)

### Fixes

- **tools:** disable colour when counting collected tests (840146f)
- **ci:** scan only the checked-out head's history with gitleaks (52ec362)
- **approvals:** pin the pushed commit and URL when a push is requested (5facafd)
- **economy:** accept rtk's ask exit code as a rewrite (a21b4ff)
- **cli:** record a missing rtk as a warning event of the run (419e80d)

### Documentation

- **adr:** propose integer micro-USD for cost and budget amounts (21ed475)
- **plan:** split phase 1 into waves of issues for cloud sessions (0a0613e)
- add contributing guide with engineering conventions (361eab9)
- add agent contributor notes with phase 1 module ownership (154cf6b)
- **adr:** accept integer micro-USD for cost and budget amounts (0c0cb63)
- allow agents to merge pull requests (c46f7a1)
- **checks:** add the manual check that a real agent cannot push (03a00e0)
- **checks:** add the manual Claude adapter contract check (4cec95b)
- **checks:** add rtk hook A/B procedure (1fcf694)
- **adr:** propose a tmux adapter for any CLI agent (c2a1db6)
- **adr:** propose a call center agent per call (0b12057)
- **adr:** treat a plan limit as the budget for tmux agents (78706ea)
- **adr:** accept the tmux adapter and the call center agent per call (db87227)
- **plan:** add the tmux adapter and the call center agent per call (1291415)
- **adr:** adopt an agent that already runs a project as its manager (2fcf5dc)
- **plan:** add adopting a running agent as project manager (4c944b5)
- **checks:** add the Phase 1 demo check and index the manual checks (6dae2ca)
- **adr:** amend ADR 0003 after review (be97db8)
- **adr:** amend ADR 0004 after review (c2af7b0)
- **adr:** amend ADR 0005 after review (99d2166)
- **plan:** align the plan with the ADR 0003-0005 review (493140d)
- **checks:** record the phase 1 manual checks (52815e3)
- **plan:** mark phase 1 done and point the next step at phase 2 (143b698)

### Tests

- **cli:** strip ANSI styling before matching help output (57ee98e)
- **adapters:** run the adapter contract against every registered adapter (128e813)
- **tools:** check for one Alembic head without pinning its revision (5735f94)
- **cli:** compare the version with pyproject.toml, not a literal (fa32d06)

### Build

- add labhq package skeleton with every phase 1 dependency (502cc37)
- **tools:** add file size, single head and collection floor guards (cb0d840)
- set version 0.1.0a1 for the phase 1 alpha (2c74334)

### CI

- add Claude PR assistant workflow (1c43ffe)
- run lint, types, tests and schema checks on every push (e189737)
- **guards:** add private-terms guard (f30a8e1)
- **guards:** add credential-reference guard for ADR 0001 (4479c49)
- **guards:** run gitleaks, private terms and credential guards (6f2aab9)
- **guards:** drop the guard self-test job now that ci.yml runs pytest (ba62623)

### Style

- **guards:** match Foundation's ruff configuration (2cfb642)

### Chores

- sync dependencies at the start of cloud sessions (9eaf1bf)
- name the labhq contributors as copyright holder (b11fcb7)

## v0.0.1-spike

### Documentation

- add initial plan, readme and MIT licence (b3d1eb8)
- **adr:** propose API key default with opt-in subscription login (f94ac88)
- **plan:** record phase 0 findings and mark spikes as passed (501300f)
- **adr:** accept subscription login as default billing (4d54f14)

### Chores

- **spike:** prove Agent SDK hook guard, interrupt, resume and approval wait (941c0bd)
- **spike:** add MCP server with built-in bearer auth and JSON responses (5abc03f)

