# Contributing to labhq

These rules bind every contributor, human or agent. Where a rule and a habit disagree, the
rule wins. Where a rule and a measured fact disagree, change the rule and record why in
`docs/adr/`.

The design and roadmap live in [`planning/plan.md`](planning/plan.md) (in Greek). Each phase
there lists acceptance criteria; an issue is done when its criteria pass as tests or guards.

## 1. Language

Every code artefact is in English: identifiers, comments, docstrings, commit messages, error
identifiers, log messages, test names, file names, branch names and migration slugs.

- Greek belongs in two places only: user-facing copy (i18n resources, templates) and planning
  documents (`planning/`, ADR prose may be either).
- File and directory names are ASCII.
- Comments explain why, never what. A comment that restates the code is noise; one that
  records a decision, a constraint or a defect is why the file survives a year.

## 2. File size

Soft limit 400 lines, hard limit 600 for hand-written source, tests included.

- Crossing 400 is a signal to split by responsibility.
- Crossing 600 fails CI. Split the file, or record a dated, justified exemption next to the
  guard's configuration.
- Exempt: generated code (migrations, clients), lock files, i18n resources, vendored code,
  data fixtures.
- One behaviour area per test file.

## 3. Control flow: dispatch is data

Prefer a registry, a lookup table or polymorphism over an `if`/`elif` chain that switches on
a variant.

- Branching on a value that names a variant (`adapter`, `event_type`, `status`, `rule_type`,
  `recipient`) is a registry: a mapping from key to handler, populated at import or
  configuration time and queried at call time.
- Configuration is data. Rates, limits, thresholds, defaults and switches live in settings or
  database rows, never in conditionals.
- Construction of a variant is a factory. The caller names what it wants; the factory decides
  which implementation answers.
- A new variant is a new registration, not an edit to a dispatcher.
- Guard clauses and early returns beat nesting. Depth over three is a refactor.

The counter-rule carries equal weight: do not add indirection for two cases that will never
become three. An `if` on a boolean is not a missing pattern. Abstraction that no second
implementation pays for is cost without return.

## 4. Decisions follow the ecosystem

Follow the mainstream, documented practice of the language. Spend novelty on the domain,
never on plumbing.

| Area | Practice |
|---|---|
| Python | Python 3.12, PEP 8, PEP 484 typing, `ruff` as the single linter and formatter, `pytest`, `pydantic` and `pydantic-settings` for validation and config, `uv` for environments, dataclasses or Pydantic models over dicts, `pathlib` over `os.path`, context managers for every resource |
| SQL | Alembic migrations are the sole schema authority. Never call `create_all` in application code. Explicit column lists. Indexes declared with the table |
| Shell | `set -euo pipefail`, quoted expansions, `shellcheck` clean. Past 50 lines it becomes Python |
| HTTP | REST semantics, correct status codes, one error envelope, cursor pagination, idempotency keys on retryable writes |
| Data | UTC instants as timezone-aware timestamps; money as integer minor units, never floats (see ADR 0002 for the cost unit); identifiers as typed references |
| TypeScript and Vue (Phase 4) | ESM, TypeScript, ESLint with the official config, Prettier, Composition API with `<script setup>`, Pinia |

When two accepted practices conflict, record the choice and its reason in `docs/adr/` and
move on. Consistency beats being locally right.

## 5. Version control

- Conventional Commits: `type(scope): summary` with `feat`, `fix`, `refactor`, `perf`,
  `test`, `docs`, `build`, `ci`, `chore`. Imperative, no trailing period, at most 72
  characters. The body explains why and references the issue (`Refs #12`, `Closes #12`).
- One logical change per commit. A commit that both moves and edits code is two commits.
- Never commit generated output, dependencies, secrets, local configuration or a database.
- Branches are named `type/short-slug`, for example `feat/scheduler`. `main` is always
  releasable and changes only through pull requests.
- Versions: SemVer for git tags (`v0.1.0-alpha.1`), PEP 440 inside `pyproject.toml`
  (`0.1.0a1`). Never put a SemVer pre-release string in `pyproject.toml`.
- Tags are annotated, one per milestone, with the acceptance evidence in the message, and
  are applied after the gate passes, never before.
- `CHANGELOG.md` is generated from history, never edited by hand.

## 6. Guards over intentions

Whatever can be checked mechanically is checked in CI: lint, format, types, file size, test
collection floor, migration and model parity, a single Alembic head, secrets and private
terms.

A guard may be strict. It may never be silent: a check that passes because it ran nothing is
worse than no check, because it turns an unknown into false assurance.

## 7. Tests

- Tests never call a real model, never need a Claude login and never touch the network. Use
  the fake adapter, which is registered like any other adapter and passes the same contract
  test.
- A behaviour that only a real model can prove (for example a token A/B measurement) is a
  documented manual check under `docs/checks/`, run on a developer machine with its result
  recorded. It is not a skipped test.
- Time is injected. No test sleeps on wall-clock time to wait for a scheduler or a reaper.

## 8. Proportionality

`spikes/` holds throwaway Phase 0 prototypes. They keep the English and `.gitignore` rules
and nothing else, and CI does not lint them. Everything under `src/`, `migrations/` and
`tests/` follows every rule above.
