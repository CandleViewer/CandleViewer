# E07-D01 — Hand-off (the operator content model for storage telemetry; `StorageUsage`, `GET /recording/storage`)

Spec of record: [E07-D01.md](E07-D01.md). This file **lifts** the parts a consumer builds or checks from, by section and row id; it restates no rule. **Input for** E16-S04 (the page's build), E16-D07 (design QA) and E07-D02 (#223, the executable check). E16-D04 (SCR-142) is the screen of record and is cited, not a recipient. (RULED BQ-16)

Status: `RULED` (§R of the spec). Base 1a42dbf7e614cc216fcfceff00294faa7bf48f49 <!-- audit:sha:base=1a42dbf7e614cc216fcfceff00294faa7bf48f49 -->. Every id below is the spec's; E07-D02 cites it as written.

## §A Checklist: decision × field (spec §3, §4.1; one row per field)

Rule: every row is `[x]` with its evidence, or `[ ]` with the reason. `✓` = answers or feeds the decision. The "Example" column holds the sample figures of the `22` example (`22` :5624–5651), never a measurement; E07-D02 adds its observed value and fills "Pass" from the baseline sample (§C item 2).

| Id    | Field                  | DL-01 | DL-02 | DL-05 | DL-06 | DL-07 | DL-09   | DL-10 | Example                                                                                                                                                                                                        | Pass              |
| ----- | ---------------------- | ----- | ----- | ----- | ----- | ----- | ------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| CK-01 | `disk_total_bytes`     | ✓     |       |       |       |       |         |       | 4000000000000 bytes <!-- audit:obs:disk_total_bytes=4000000000000 bytes -->                                                                                                                                    | [ ]               |
| CK-02 | `disk_used_bytes`      |       |       |       |       |       |         |       | 1204000000000 bytes <!-- audit:obs:disk_used_bytes=1204000000000 bytes -->                                                                                                                                     | [ ] exception X-1 |
| CK-03 | `disk_free_bytes`      | ✓     |       |       |       |       |         |       | 2796000000000 bytes <!-- audit:obs:disk_free_bytes=2796000000000 bytes -->                                                                                                                                     | [ ]               |
| CK-04 | `projected_full_at`    | ✓     |       |       |       |       |         |       | 2028-03-27T10:31:03Z <!-- audit:obs:projected_full_at=2028-03-27T10:31:03Z -->                                                                                                                                 | [ ]               |
| CK-05 | `daily_growth_bytes`   | ✓     |       |       |       |       | ✓       |       | 1450000000 bytes per day <!-- audit:obs:daily_growth_bytes=1450000000 bytes per day -->                                                                                                                        | [ ] F-04          |
| CK-06 | `tiers[]`              | ✓     |       |       |       |       | partial | ✓     | 3 rows: questdb 640000000000 bytes, parquet 548000000000 bytes, postgres 16000000000 bytes <!-- audit:obs:tiers=3 rows: questdb 640000000000 bytes, parquet 548000000000 bytes, postgres 16000000000 bytes --> | [ ] D04-G1        |
| CK-07 | `symbols[]`            |       |       | ✓     | ✓     |       |         |       | 2 rows: BTCUSDT 812340221100 bytes, ETHUSDT 1220004410 bytes <!-- audit:obs:symbols=2 rows: BTCUSDT 812340221100 bytes, ETHUSDT 1220004410 bytes -->                                                           | [ ] X-2           |
| CK-08 | `generated_at`         |       |       |       |       | ✓     |         |       | 2026-09-14T10:31:03.000Z <!-- audit:obs:generated_at=2026-09-14T10:31:03.000Z -->                                                                                                                              | [ ]               |
| CK-09 | `cap_bytes`            | ✓     |       |       |       |       |         |       | 2000000000000 bytes <!-- audit:obs:cap_bytes=2000000000000 bytes -->                                                                                                                                           | [ ]               |
| CK-10 | `level`                | ✓     | ✓     |       |       |       |         |       | 0 <!-- audit:obs:level=0 -->                                                                                                                                                                                   | [ ]               |
| CK-11 | `write_gate`           |       | ✓     |       |       |       |         |       | open <!-- audit:obs:write_gate=open -->                                                                                                                                                                        | [ ]               |
| CK-12 | `write_gate_reason`    |       | ✓     |       |       |       |         |       | null <!-- audit:obs:write_gate_reason=null -->                                                                                                                                                                 | [ ]               |
| CK-13 | `accelerate_retention` |       | ✓     |       |       |       |         |       | false <!-- audit:obs:accelerate_retention=false -->                                                                                                                                                            | [ ]               |

Decisions with **no** field (spec §3): DL-03 (D04-G7), DL-04 (health report, D04-CG1), DL-08 (D01-G1). E07-D02 reports them as "not expressible today" once, not as a defect again (§C item 7).

## §B The states (spec §7.2, §9.1)

| Id           | State                                                  | How it is reached                                        | Field that shows it                        | Words                                        | Expressible today       |
| ------------ | ------------------------------------------------------ | -------------------------------------------------------- | ------------------------------------------ | -------------------------------------------- | ----------------------- |
| ST-01..ST-03 | healthy · near limit · auto-record paused              | `level` 0, 1, 2                                          | `level`, `accelerate_retention`            | `D04`'s `storage.headline.0`..`.2`           | yes                     |
| ST-04        | recording stopped for symbols without an open position | `level` 3, gate `closed`, reason `disk_halt`             | `level`, `write_gate`, `write_gate_reason` | `storage.headline.3`, `storage.level3.fact`  | yes                     |
| ST-05        | recording volume refused                               | reason `volume_refused`                                  | `write_gate_reason`                        | `storage.volume_refused`                     | yes                     |
| ST-06        | stale sample                                           | the last pass older than 3 × 60 s                        | `generated_at`                             | `storage.stamp.stale`                        | yes                     |
| ST-07        | export check failed, hot data kept                     | a row-count mismatch aborts the export before it commits | none                                       | _`storage.export_retained`_ (PROPOSED)       | **no** (D01-G1)         |
| ST-08        | schema differs from the registry                       | a hot table's columns differ from its registered set     | none                                       | _`storage.schema_drift`_ (PROPOSED)          | **no** (D01-G1)         |
| ST-09        | a tier unreachable                                     | a component `state` other than healthy                   | `HealthReport.components[]`                | `storage.tier.unreachable`                   | yes, on another surface |
| ST-10        | migration pending                                      | version delta                                            | none                                       | `storage.migration.banner`                   | **no** (D04-G7)         |
| ST-11        | writes behind the feed                                 | backlog above the PROPOSED threshold                     | the recorder topic                         | `storage.lag.banner`                         | yes, on another surface |
| ST-12        | figures not available yet                              | 503 before a first sample, or with no budget             | the status code                            | `storage.unavailable`, _`storage.not_ready`_ | yes                     |
| EM-01..EM-08 | the empty, error and stale states                      | spec §9.1                                                | as the rows say                            | as the rows say                              | as the rows say         |

## §C What E07-D02 needs (BQ-19; eight items) (RULED BQ-19)

1. **Stable row ids:** `DL-nn`, `ST-nn`, `EM-nn`, `RS-nn`, `CK-nn`, `F-nn`, `D01-Gn`, `D04-Gn`, `X-n`, `U-nn`. Cite them as written.
2. **The baseline payload rule (spec §5):** capture the sample from the E16-T08 route's contract test output, never from the `22` example and never from `build_storage_usage` (F-05).
3. **The state table:** §B above, with "expressible today".
4. **The enum lists:** `level` 0 · 1 · 2 · 3 <!-- audit:enum:level=0 · 1 · 2 · 3 -->; `write_gate` open · closed <!-- audit:enum:write_gate=open · closed -->; `write_gate_reason` disk_halt · volume_refused · null <!-- audit:enum:write_gate_reason=disk_halt · volume_refused · null --> (open-ended for readers, `22` :20134–20139); `tiers[].tier` questdb · parquet · postgres <!-- audit:enum:tier=questdb · parquet · postgres -->.
5. **The reconciled names (spec §11):** 15 <!-- audit:count:names=15 --> names, 3 <!-- audit:count:names.absent=3 --> absent (D01-G6 and the two actions with no route).
6. **The no-path rule list (spec §9.4):** the patterns, the fields and messages to scan; the tool of D01 carries the pattern list so E07-D02 imports it.
7. **The accepted exceptions:** X-1, X-2, and the three decisions with no field, so a known gap is not reported twice.
8. **The calendar:** E07-D02 is Sprint 03 (2026-10-09 <!-- audit:cal:s03.start=2026-10-09 -->..2026-10-15 <!-- audit:cal:s03.end=2026-10-15 -->), already past; D01's merge is the unblock.

## §D Gaps and owners (spec §15.2; none is filed, none edits `22`)

| Id     | Gap                                                               | Owner                                                          | Needed by                          |
| ------ | ----------------------------------------------------------------- | -------------------------------------------------------------- | ---------------------------------- |
| D04-G1 | per-tier growth and projection                                    | `E16-T07 · area/recorder-replay`                               | `E16-S04` (#486)                   |
| D04-G7 | schema version, target version, pending count                     | `22 · area/backend-platform`                                   | `E16-S04` (#486)                   |
| D04-G8 | the vacuum route and job kind                                     | `22 · area/backend-platform`                                   | `E16-S04` (#486)                   |
| D01-G1 | `tier_alerts[]`: export-verification and schema-difference states | `22 · area/backend-platform`, `E16-T07 · area/recorder-replay` | `E07-D02` (#223); `E16-S04` (#486) |
| D01-G2 | the three tier codes registered in the error surface              | `22 · area/backend-platform`                                   | `E07-D02` (#223)                   |
| D01-G3 | `daily_growth_bytes` nullable                                     | `E16-T07 · area/recorder-replay`                               | `E16-S04` (#486)                   |
| D01-G4 | a tier-migration route, job kind and audit record                 | `22 · area/backend-platform`                                   | `E16-S04` (#486)                   |
| D01-G5 | the `symbols[]` cap and order in the schema                       | `22 · area/backend-platform`                                   | `E07-D02` (#223)                   |
| D01-G6 | the metric `pg_migration_pending`                                 | `E07-T02 · area/backend-platform`                              | `E07-D02` (#223)                   |
| D01-G7 | `projection_wall`                                                 | `22 · area/backend-platform`                                   | `E16-S04` (#486)                   |

## §E The units, in one place (spec §8)

U-01..U-09 are the rules; the tool fills the examples: 1,188.0 <!-- audit:fmt:used_gb=1,188.0 --> GB of 2,000.0 <!-- audit:fmt:cap_gb=2,000.0 --> GB (59.4 <!-- audit:fmt:budget_pct=59.4 --> %), 1.45 <!-- audit:fmt:growth_gb_day=1.45 --> GB/day, about 560 <!-- audit:fmt:runway_days=560 --> days (2028-03-27 <!-- audit:fmt:full_date=2028-03-27 -->), Sampled 10:31:03 <!-- audit:fmt:sample_time=10:31:03 --> UTC (every 60 s). An unknown projection reads "No projection yet" (U-05). `retention_days` `null` reads "No limit" (U-06).

## §F Who applies what

| A   | Target                                  | Applied by             |
| --- | --------------------------------------- | ---------------------- |
| A-1 | `14` SCR-142 pointer line (RULED BQ-11) | this PR (content-only) |
| A-2 | `04` SR-096 wording                     | `04`'s owner           |
| A-3 | `22` `write_gate_reason` description    | `22`'s owner           |

## §G Sign-off

Pending: the orchestrator's design approval plus the QA record; the owner's walkthrough "post-Done (#2701)" (spec §16.3). No participant was seen and no session was run (spec §16.2). (RULED BQ-18)
