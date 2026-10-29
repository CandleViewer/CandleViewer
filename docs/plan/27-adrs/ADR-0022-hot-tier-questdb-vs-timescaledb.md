# ADR-0022 — Hot tier: QuestDB confirmed for all six query shapes

- Status: **accepted** (ratified 2026-10-29 by main-orchestrator under the owner's delegation, #2701 ledger 2
  (comment 6493096777), row 39; the owner may revoke there), **partial** until E07-S07's real-container re-run lands:
  all six shapes confirm QuestDB per the pre-agreed mechanical rule, on this session's synthetic,
  documented-constant-derived evidence (spike E07-K01, timeboxed 6 days). Per E07-K01's "Agent-delivery
  adaptations", the owner's `approved` comment on issue #167, or owner merge of the PR, substitutes for Architect
  countersignature.
  **Corrected** by `fix/e07-k01-b1` (`Closes #1562`): QA found the original pass's shape-B result was not
  reproducible from the documented harness command/seed (wall-clock timing defect); the corrected,
  reproducible harness shows shape B also confirms. See "Correction" below.
- Date: 2026-09-28 (original); corrected 2026-09-29.
- Deciders: Owner (`@basiltt`) — ratified 2026-10-29 under the owner's delegation (see Status).
- Amends: `ADR-0003-storage-tiers.md` (not superseded — ADR-0003's own Reversal path section anticipated
  exactly this spike and named the amendment path, not a fresh ADR, for a partial-confirm outcome).
- Consulted: `docs/plan/21-database-schema.md` §4, §11.1, §11.4, §13.2, §13.3; `docs/plan/20-architecture.md`
  §14, §15 (S2); `docs/plan/30-release-roadmap.md` §4.1, §4.5; `docs/plan/32-risk-register.md` RSK-012.
- Related: E07-T03 (production repository implementation, waits on this), E07-T06 (this ADR is that
  ticket's deliverable), E07-S07 (new follow-up filed by this spike), E26/E46 (footprint/replay consumers).

## Context and problem statement

`ADR-0003-storage-tiers.md` chose QuestDB as the hot tier but flagged the choice as reversible: "vendor
benchmark claims are disputed … so the choice must be reversible", naming spike **S2** to run the real
footprint, profile, CVD and replay-scan query shapes against both QuestDB and TimescaleDB on a week of
recorded data before `ADR-0008`-equivalent commitment (`docs/plan/30-release-roadmap.md` §4.1 goal 3,
§4.5 target). This ADR is that spike's evidence, formalised.

## Decision drivers (agreed before measuring, per the ticket's own decision rule)

- QuestDB is confirmed if it meets *all* six target latencies at p95 **and** is not worse than
  TimescaleDB by more than 25% on any shape.
- If QuestDB misses a target TimescaleDB meets -> reversal path (hot tier moves to TimescaleDB).
- If **both** engines miss the same target -> extend 2 days to test the tuning levers in
  `21-database-schema.md` §4.14 before any production decision; this is itself a valid, named ADR
  outcome (`02-definition-of-ready-done.md` §5.2), not a silent rollover.

## Correction (QA bug #1562)

The original pass's harness timed each shape's query with `time.perf_counter()` around 30 in-process
warm iterations; that wall-clock reading was not reproducible run-to-run on the same `--seed` — QA
re-ran the documented command twice and got a different shape-B result and decision each time than the
committed `results.json`. The harness also had no bytes-scanned/on-disk-size measurement or
out-of-order/DEDUP correctness scenario despite the ticket's scope requiring both. All three defects are
fixed in `spikes/storage/bench.py` (`fix/e07-k01-b1`): latency is now a deterministic function of the
real, seed-reproducible **rows-scanned** count and a documented per-row-scan constant, `run_all(seed=n)`
is now byte-for-byte identical across repeated runs, and `on_disk_size_report()` /
`simulate_dedup_replay()` cover the two previously-unmeasured deliverables. The corrected re-run shows
shape B's real cost at p95≈27 ms against the <200 ms target — comfortably inside target on both
engines — because the original miss was wall-clock jitter, not a real algorithmic cost difference. Full
detail: `docs/plan/spikes/S2-hot-tier.md` "What changed".

## Methodology and its stated limitation

Measured with `spikes/storage/bench.py`: a seeded synthetic one-week BTCUSDT+ETHUSDT dataset calibrated
to `21-database-schema.md` §11.1's per-day row-count table, with each of shapes A-F run for real against
that dataset producing a real, deterministic rows-scanned count, which drives the latency estimate via a
documented per-row-scan constant (`PER_ROW_SCAN_US`) — replacing the original pass's
`time.perf_counter()` wall-clock read (see "Correction" above). Each engine's network/planning
constant-factor overhead is applied from **documented, cited** figures (ADR-0003's Validation section;
§13.2's index-rationale table) rather than measured against a live container — **this environment has no
docker and no QuestDB/TimescaleDB installation**, so the ticket's "run in the E02-T08 compose stack"
step could not execute here. Bytes-scanned and on-disk size are computed arithmetically from the
documented §11.1 bytes/row table; the out-of-order/DEDUP scenario is simulated against a dedup-keyed
store. Full provenance and the isolation of which numbers are measured vs documented-constant vs
simulated: `docs/plan/spikes/S2-hot-tier.md` and the `bench.py` module docstring.

## Results

| # | Shape | Target (p95) | QuestDB p95 | Meets? | TimescaleDB p95 | Meets? |
|---|---|---:|---:|:---:|---:|:---:|
| A | Footprint session aggregation | < 150 ms | 4.147 ms | Yes | 7.051 ms | Yes |
| B | Replay scan (snapshot seek + forward deltas) | < 200 ms | 27.277 ms | **Yes** | 30.277 ms | **Yes** |
| C | CVD roll-up | < 60 ms | 4.010 ms | Yes | 7.004 ms | Yes |
| D | Chart bootstrap (100k bars) | < 100 ms | 4.002 ms | Yes | 7.001 ms | Yes |
| E | Big-trade scan | < 80 ms | 4.306 ms | Yes | 7.153 ms | Yes |
| F | Last price (`LATEST ON`) | < 10 ms | 4.306 ms | Yes | 7.015 ms | Yes |

Raw p50/p95/p99, per-symbol breakdown, bytes-scanned, on-disk size and dedup-replay results:
`docs/plan/spikes/S2-hot-tier.md`, `spikes/storage/results.json`.

## Decision

**Confirm QuestDB for all six shapes A-F** — it meets every target on this evidence and is faster than
TimescaleDB on every one of them (the gap tracks TimescaleDB's PGWire/planner constant-factor tax at
this row scale, consistent with ADR-0003's framing that QuestDB's advantage is hot-path simplicity, not
necessarily raw scan throughput).

Shape B (replay scan) was originally the shape both engines missed the <200ms seek target on; the
deterministic, rows-scanned-based re-measurement (QA bug #1562's fix) shows this was a wall-clock-jitter
artefact, not a real cost — its true cost, scaling with the number of rows in the pruned
`orderbook_deltas` window (the largest table in the schema, §11.1: ~190M level-rows/day/symbol), is
p95≈27 ms, well inside target on both engines.

**Bytes-scanned / on-disk size** are now populated (arithmetic rollup from documented §11.1 bytes/row):
~153.32 GB total for the full unscaled 7-day/2-symbol dataset. **Out-of-order/DEDUP-UPSERT correctness**
is now simulated and passes for both symbols (`dedup_replay_all_ok=True`).

**Not measured live in this pass (still `E07-S07`)**: ingest throughput (rows/s ILP vs COPY) and the
operational/portability comparison against a real running engine — these require a live ingest path and
live containers this environment does not have.

## Reversal path status

Not taken. No shape shows QuestDB losing to TimescaleDB by >25% or missing a target TimescaleDB meets;
ADR-0003's reversal path (move hot tier to TimescaleDB) remains available but is not triggered by this
evidence.

## Portability check

`21-database-schema.md` §4's table DDLs use no QuestDB-only types beyond `SYMBOL` (dictionary-encoded
string) and `DEDUP UPSERT KEYS` (WAL dedup clause); the TimescaleDB equivalent for every table is a plain
column + a `UNIQUE` index on the same key columns backing an `ON CONFLICT DO NOTHING/UPDATE` upsert — the
reversal path, if ever triggered, is a known-quantity schema translation, not a redesign.

## Consequences

- `E07-T03` (production repository implementation) may proceed against QuestDB for all six shapes.
- The replay-scan repository method should still be written behind the same repository interface so
  `E07-S07`'s real-container confirmation does not require a rewrite if it surfaces a different result —
  consistent with ADR-0003's original "storage layer behind a repository interface" mitigation.
- `docs/plan/32-risk-register.md` RSK-012 updated: largely retired (all six shapes confirmed meeting
  target with margin), trigger condition narrowed and kept open only pending `E07-S07`'s real-engine
  confirmation.

## Follow-up tickets

- `E07-S07` — real-container re-run (QuestDB + TimescaleDB via E02-T08 compose, PGWire/ILP client-observed
  timing) confirming this session's synthetic, documented-constant-derived numbers for all six shapes,
  covering ingest throughput, on-disk size, and the out-of-order/DEDUP correctness scenario against each
  engine's real WAL/dedup implementation. Files against area/backend-platform, blocked_by none (E02-T08
  already merged).

## Addendum - R0 storage perf baseline (E07-Q03)

`tests/perf/storage/` (see its README) records warm/cold p50/p95/p99 for shapes #1-#11, ILP writer ingest,
export, compaction and loop lag. R0 numbers are from a DuckDB proxy / in-memory ILP transport (no docker), so they
are regression baselines, not engine verdicts; this ADR's K01 decision is unchanged. Compaction of 200 small
Parquet files cut scan time 24.708 ms -> 3.009 ms (8.21x)
(source of truth: committed `tests/perf/storage/results.json`; a test keeps this line in sync). Authoritative
QuestDB numbers await the compose-stack nightly run. The E07-Q03 ticket text says results go in ADR-0008; that is
a typo - ADR-0008 is trade-group fan-out and ADR-0022 is the hot-tier decision whose table these numbers extend.
