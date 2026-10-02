# 0002. Store cost and budget amounts as integer micro-USD

## Status

Accepted (2026-10-02).

## Date

2026-10-02

## Context

The conventions require money as integer minor units, never floats. The plan's data
model names its columns `budget_minor` and stores `cost_events` in minor units.

The minor unit of USD is the cent. The Agent SDK reports the cost of a run as
`ResultMessage.total_cost_usd`, a float. The Phase 0 spike measured single runs at
0.0097, 0.0172, 0.0210 and 0.0384 USD (`spikes/agent_sdk/RESULTS.md`). In cents,
most of these round to 1 or 2, and the cheap ones lose half their value. Summed over
hundreds of small runs, the rounding error decides whether a budget's 80% warning
and 100% stop fire at all.

## Options considered

1. Cents (`*_minor`). Matches the general rule literally. Loses sub-cent precision on
   every run, which breaks budget enforcement for small runs.
2. Decimal or numeric strings. Exact, but SQLite has no native decimal type, so
   comparisons and sums in SQL become string or float operations.
3. Integer micro-USD (`*_micros`, 1 USD = 1,000,000). Exact to six decimal places,
   more than the SDK reports in practice. A 64-bit SQLite integer holds about
   9.2 trillion USD in micros. Sums and comparisons stay integer arithmetic in SQL.

## Decision

Option 3. Every cost and budget amount is an integer number of micro-USD, in columns
suffixed `_micros` (`budget_micros`, `cost_micros`). The rule "money as integer minor
units" still holds; the unit is the micro-dollar instead of the cent.

Conversion from the SDK goes through `Decimal(str(total_cost_usd))`, scaled by
1,000,000 and rounded half-up to an integer, in one function that has its own tests.
No code path multiplies the float directly.

USD is the only currency, because the SDK reports only USD.

## Consequences

- The plan's `budget_minor` columns become `budget_micros`.
- Display code formats micros as dollars with a fixed number of decimals; it never
  stores the formatted value.
- If Anthropic ever reports cost in another currency or a finer unit, revisit this ADR.
