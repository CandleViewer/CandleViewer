# ADR-0025 — Audit query and index strategy

- Status: **accepted** (ratified 2026-10-29 by main-orchestrator under the owner's delegation, #2701 ledger 2
  (comment 6493096777), row 39; the owner may revoke there; measured in CI on 10 M rows). Gap: the ticket names no
  write-latency budget, so the Q2 result (below) cannot be declared "meeting budget".
- Date: 2026-10-02
- Deciders: Owner (`@basiltt`) — ratified 2026-10-29 under the owner's delegation (see Status).
- Numbering note: the ticket text says "ADR-0021"; ADR-0021..0024 are already taken, so this is the next
  free number, 0025 (per the delivery adaptations).
- Related: E42-K01 (this spike), E42-T02 (consumer), `docs/plan/21-database-schema.md` §3.10.1,
  `docs/plan/spikes/E42-K01.md`.

## Context

US-ADMIN-009 requires first-page audit search over 10 M rows in <=2 s (SCR-135: <=400 ms p95 for common
filters). The existing indexes (`ix_audit_time/actor/action/object`, partial `ix_audit_sev`) are single-lead-
column. The hash-chain trigger and its advisory lock are untouched by any option here.

## Decision

All numbers come from CI runs 37011721464 (queries) and 37031566428 (write path, cold cache) (`integration / audit-query-plan`) with 10 M synthetic rows on
PostgreSQL 16.15, measured directly with no extrapolation. Full tables: `docs/plan/spikes/E42-K01.md`.
Raw data: `E42-K01-ci-report.json`.

1. **Add** partial `ix_audit_hisev ON audit_log (event_ts DESC) WHERE severity IN ('error','critical')`.
   It fixes the only filter combination that misses 400 ms p95 on today's set (`severity + actor`:
   442.6 ms → 0.92 ms).
2. **Add** `(actor_user_id, action, event_ts DESC)`: actor+action goes from 0.15 ms to 0.08 ms. It is not
   needed for the budget, but it is cheap (see the Q2 table for its measured write cost).
3. **Add** the GIN full-text index on `before_state || after_state`. Without it, a selective token misses
   2 s in every query form (30.9 s wide, 2.6 s even within 30 days). With it, the CTE form takes 31 ms.
   The GIN index is part of the measured write cost above. `CREATE INDEX CONCURRENTLY` took 139 s and produced
   a 256 MB index, while 2,469 concurrent inserts went through (p99 6.8 ms). **CONCURRENTLY is feasible.**
4. Full-text `q` must use **selectivity-aware dispatch**: CTE+GIN for selective tokens (≤ 31 ms) and the
   naive keyset walk for common tokens (≤ 1.6 ms). No single form meets 2 s for both.
5. **Reject** BRIN (no gain). Range partitioning is **not needed** at 10 M rows.

All budgets are met with items 1–4. **Not met without them:** `severity + actor` on the existing set, and
full text in any single query form.
Write cost (Q2, run 37031566428): single-row INSERTs through the chain trigger and its advisory lock,
paced at 500/s (assumed; no production rate is documented). Existing set: p50 1.86 / p99 2.21 ms
(20k samples). Full recommended set, f + GIN measured together: p50 5.83 / p95 7.75 / p99 8.71 ms
(100k samples), so about +4 ms p50 and +6.5 ms p99 per INSERT. Per-set figures are in the spike note.
Limits: CI runner with a warm cache for queries, 20 samples per query (p99 = max), sets a-f use 20k write
samples, rolled-back transactions exclude commit fsync, and no write-latency budget exists to compare to.

## Consequences

- #1710 ships one migration with the three indexes, built `CONCURRENTLY` (about 2.5 min at 10 M rows).
- E42-T02 implements the filters on the new set and full text per item 4 (#1711).
- The indexes add no new read path beyond the existing `audit_log` grants. The hash-chain trigger and
  its advisory lock are untouched.
- RSK-052 is downgraded: the common-token case is solved by dispatch. What remains is the risk of
  mis-dispatch when the estimate is wrong.

## Follow-ups (filed, parent E42 #63)

- #1710: migration adding the three indexes.
- #1711: selectivity-aware full-text dispatch in E42-T02.
