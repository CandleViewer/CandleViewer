# ADR-0027 — Journal analytics query tier

- Status: **accepted** (ratified 2026-10-29 by main-orchestrator under the owner's delegation, #2701 ledger 2 (comment 6493096777), row 39; the owner may revoke there). The ticket text says "ADR-0016"; 0016..0026 are taken, so this is the next free number.
- Date: 2026-10-03
- Deciders: Owner (`@basiltt`) — ratified 2026-10-29 under the owner's delegation (see Status).
- Related: E41-K01 (#959), E41-T03 (consumer), `docs/plan/spikes/E41-K01.md`, `docs/plan/21-database-schema.md` §3.7.

## Context

`GET /journal/analytics` needs totals + seven breakdowns + equity curve for up to 10 000 trades
(SCR-095 <=800 ms interactive; breakdowns <=2 s). Candidates: Postgres 16, DuckDB over the
`journal_trades/ ym=…` Parquet layout, or a hybrid (Postgres hot window + DuckDB cold, unioned).

## Decision

**Postgres only.** `/journal/analytics` is computed in one code path from `journal_trades` +
`journal_trade_tags` with the existing indexes (`ix_jt_time/symbol/account/outcome/setup`, `ix_jtt_tag`).
Parquet stays the archive format (E16 roll-off) and is **not** on the analytics read path. No covering
index and no materialised rollup now.

Evidence (full tables for 1k/10k/100k: spike note; `numeric(38,18)`, 6 accounts, ~40 tags, ~3 tags/trade,
7 reps; p50 / p95 ms):

| Query @ 10 000 trades | Postgres | DuckDB | Hybrid | PG+covering |
|---|---|---|---|---|
| totals | 48 / 57 | 21 / 24 | 21 / 25 | 17 / 19 |
| totals + 7 breakdowns | **298 / 340** | 158 / 188 | 303 / 452 | 386 / 3339 (noisy) |
| equity curve (trade) | 232 / 276 | 287 / 2035 | 351 / 990 | not measured |
| MAE/MFE payload | 75 / 88 | 213 / 245 | 266 / 3247 | not measured |
| filtered | 3 / 5 | 21 / 25 | 31 / 36 | 5 / 5 |

Postgres meets <=2 s with ~6x headroom at 10 000 trades. At 100 000 rows Postgres breaks the budget
(breakdowns 4.3 s p50); DuckDB is faster there but still ~3 s, so a second engine would not fix it, whereas
a rollup (0.5 s, partial breakdowns) would. This deployment (single owner, a few managers) will not reach
100k closed trades in R3–R5.

**Revisit trigger:** `journal_analytics_query_seconds` p95 > 1 s at the 10k range, or > 50 000 rows in
`journal_trades`. Consider a daily rollup before any second engine.

## Rejected

- **DuckDB/Parquet only:** wins on totals/breakdowns by small margins, loses on filtered and MAE/MFE, adds
  a freshness seam and a second RBAC enforcement point.
- **Hybrid:** most variable at 10k (p95 up to 3.2 s) plus boundary cost (`avg` is not additive; must carry sum+count).
- **Covering index:** no consistent gain at 10k; extra write cost on a table updated on every close.
- **Materialised rollup:** cannot serve tag/hour/day-of-week breakdowns without more dimensions; staleness.

## Freshness / consistency contract

Single authoritative store: **maximum staleness 0 s**. A just-closed trade is visible as soon as its
`journal_trades` row commits; the UI needs no staleness indicator. (If a rollup is added later: staleness
<= refresh interval, the response carries `as_of`, and the UI shows "as of hh:mm".)

## RBAC

Account scoping is a mandatory predicate applied inside the base subquery (`exchange_account_id IN
granted_accounts`), built server-side from the session before any filter or join. A client-supplied
`account` filter is intersected with the grant, never unioned. Demonstrated in
`services/api/tests/unit/journal_bench/`: a Manager requesting an ungranted account gets the empty scope,
and non-UUID ids are rejected. Production must use bound parameters (the bench builds literals only for
synthetic ids). A DuckDB-over-Parquet path has no row scoping at all, a further reason to reject it.

## Observability

`journal_analytics_query_seconds` histogram, labels `group_by` (cardinality bucket) and `tier` (`postgres`).

## Caveats / residual risk (recorded for E41-T03)

Measured on a Windows 11 workstation with PostgreSQL 16.4 (EDB binaries) and DuckDB 1.5.6, **not** the WSL
reference machine (unavailable to the agent), so absolute numbers carry noise (several p95 outliers). The
~6x headroom makes the decision robust; re-run on WSL with `make bench-journal`. Hour/day/week equity
granularities were not benchmarked separately (cheaper than `trade` granularity after bucketing). The bench
table is a column subset of the production `journal_trades`.
