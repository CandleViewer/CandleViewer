# ADR-0035 — Replay source tier, read-ahead and seek strategy

- Status: **proposed** (draft from spike E26-K01; finalised in E26-T07; owner approval pending).
- Date: 2026-10-11
- Deciders: Owner (`@basiltt`), Architect.
- Numbering note: the ticket (E26-K01, #622) says "ADR-0018". 0018 is taken (monorepo tooling), and
  0031 is reserved by E45-K01, so this record uses the next free number after 0034.
- Related: E26-K01 (#622), E26-T04 (seek), E26-T07 (finalise), E26-Q03 (CI bench), E16-T05 (roll-off),
  `24-internal-schemas.md` §13.7, `30-release-roadmap.md` §6.3 exit #8, `06-performance-and-load-standard.md`
  budget #15, ADR-0003 (storage tiers).
- Evidence: [`notes/e26-replay-seek.md`](../notes/e26-replay-seek.md) (SYNTHETIC 200-depth day, laptop,
  5 runs per cell), harness `services/api/bench/replay_seek/`.

## Context

§13.7 seeks by loading a snapshot anchor (every `snapshot_interval_s`, default 300 s), re-applying deltas,
restoring `BuilderState`, and then warming up metrics. Roadmap exit #8 requires 1 s at 200 depth. Budget
#15 requires 100× playback. Neither was measured before this spike.

## Findings (synthetic dense 200-depth, worst-case target, cold tier)

| Option                                            |   Seek p95 |
| ------------------------------------------------- | ---------: |
| 300 s, frame-by-frame re-apply (§13.7 as written) |      8.6 s |
| 60 s, frame-by-frame                              |      3.7 s |
| 30 s, frame-by-frame                              |      1.0 s |
| 60 s, collapsed deltas                            | **0.41 s** |
| 30 s, collapsed deltas                            |     0.28 s |

Delta re-apply takes 75–95 % of seek time. Cold Parquet reads ran at ~9 M events/s and the
`(ts_event, seq)` merge at ~2.6 M events/s. The busiest minute at 100× needs 0.41 M events/s.

## Decision (proposed)

1. **Snapshot interval 60 s for 200-depth recording** (E16 recorder change). Snapshots then cost +18 MB
   hot / +2.2 MB cold per symbol-day.
2. **Seek collapses deltas**: keep the last write per `(side, price)` over [anchor, target], then build the
   book once. The result must equal frame-by-frame application (verified against the next snapshot in
   every spike run). Live and replay _playback_ still apply every frame.
3. **Read-ahead: a streamed cursor feeding a bounded prefetch window of 30 s of replay time** (Arrow
   batches; overflow policy: the reader blocks, and the replay clock slows rather than drops — §13.7).
4. **`source_tier='auto'`**: use cold when the whole range is in manifested Parquet partitions, else hot.
   Never mix tiers within one session until T04 proves the roll-off seam. _Provisional until the CI
   QuestDB leg reports._
5. **No replay-side book checkpoint cache.** The fallback, if E16 declines (1): a lazily built 60 s
   replay-side book checkpoint (Mitigation B).
6. Metric: `replay_seek_duration_ms{stage}` with `stage ∈ {anchor_load, delta_apply, builder_restore, warmup}`.

## Consequences

- §13.7's "default 300 s" text changes to 60 s when E16 accepts the change (contract-first PR, not this spike).
- Warm-up (~170 ms) is the next-largest stage. T04 should add an indicator checkpoint beside `BuilderState`.
- Follow-ups: #2223 (E16 interval), #2224 (seek path + metric), #2225 (re-measure on a recorded day).
- Every number here is synthetic and measured on a laptop. E26-Q03 re-baselines on a recorded day on the WSL target before enforcing a gate.

## Alternatives rejected

- **Keep 300 s + collapse**: 1.3 s p95, which fails the 1 s target.
- **30 s**: twice the snapshot disk of 60 s, for a margin the budget does not need.
- **Prefetch the whole session**: RSS grows with session length (~0.4 KB/event, ~75 GB for a 190 M-row dense day). Rejected.
