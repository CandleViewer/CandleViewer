# ADR-0033 — Renko brick sizing and series rebuild semantics

- Status: **accepted** (ratified by the owner 2026-10-09; decision record on #1778, item N); Addendum 1
  2026-11-03 (as built, E12-K02).
- Date: 2026-10-07
- Deciders: Owner (`@basiltt`) — **ratified 2026-10-09** as written (decision record on #1778, 2026-10-09).
- Numbering note: the ticket (E12-K01, #525) says "ADR-0014"; 0014 is taken (Observability) and 0031 is reserved by
  E45-K01 (`ADR-0031-resilience-and-chaos`, not yet on `main`), so this is the next free number after 0032.
- Related: E12-K01 (#525, this spike), E12-T01 (#344, `BarSpec`), E12-S04 (Renko builder), E12-S12
  (rebuild API), E12-T05 (param parsing), E12-T07 (rebuild CI budget), `24-internal-schemas.md` §3.1/§3.3/§3.4,
  `22-api-openapi.yaml` `/market/bars`, `23-ws-protocol.md` §6.1, `30-release-roadmap.md` §12.
- Evidence: `services/api/bench/renko_rebuild/` (harness), `docs/research/e12/renko-rebuild-results.json` (raw run).

## Context

Two questions blocked E12-S04 / E12-S12: what `renko` + `atr:14` means given that `BarSpec` has only
`range_ticks`, and whether "rebuild of 1M prints <= 10 s, cancellable" is reachable and how cancellation works.

## Decision 1 — ATR bricks: defer `atr:*` to R2; R1 accepts integer ticks only

The contract disagreement is real: `22-api` (param table) and `23-ws` §6.1 promise `atr:14`, while
`24-internal-schemas` §3.1 has no ATR field and says nothing about the source series or cadence.

**R1 rule:** `renko.param` is a base-10 integer tick count. The merged E12-T01 parser (`bars/spec.py` `_UINT`) accepts
`^[1-9][0-9]{0,17}$` within the 24-character `param` bound; **E12-T05 enforces that same pattern** (this ADR does not
narrow it to fewer digits), and the 422 path applies to everything outside it. Anything else, including
`atr:14`, is rejected with HTTP 422 `validation_failed` (WS: the matching subscribe error), `detail` =
`"ATR bricks are not available yet. Enter a brick size in ticks."` (the UI renders this as text, no silent
fallback). `BarSpec` is unchanged in R1; `atr` stays a reserved word in the param grammar.

**Doc changes proposed** (separate contract-first PR, not in this spike — governed files, C-6.1):

1. `22-api-openapi.yaml` `/market/bars`: renko row becomes "brick size in ticks (`atr:N` reserved, R2)";
   drop `atr:14` from the `param` examples; add the 422 example above.
2. `23-ws-protocol.md` §6.1: same wording for `renko`.
3. `24-internal-schemas.md` §3.3: add the R2 reservation below as a paragraph.

**Breaking-change classification (C-6.1/C-6.3).** Rejecting `atr:14` narrows input that `22-api` and `23-ws`
§6.1 currently document as accepted, so under C-6.3 ("tightening a type", "changing semantics") it **is** a
breaking contract change on paper. No consumer can depend on it: no builder, no `/market/bars` renko path and no
generated client call exists yet (E12-S04 is unstarted). The follow-up contract PR therefore ships as
`docs(protocol)!:` with a `BREAKING CHANGE:` footer citing ADR-0033 and states "no shipped implementation; no
`/v2` needed", rather than as a wording tweak. If any implementation accepting `atr:*` lands first, this
argument fails and a `/v2` plus deprecation entry is required.

**Why defer rather than ship:** ATR over the renko series is circular, so a coherent form needs a second
series, a warmup rule and a freeze rule — three new contract surfaces on a rung-2 (cuttable) feature. Deferral
costs nothing the roadmap promised for R1 (fixed-size Renko is intact).

**R2 reservation (the only coherent design; prototyped and verified):**

| Aspect            | Rule                                                                                                                                                                                                                                                                                                                                                                                                   |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| (a) Source series | ATR is Wilder ATR(`period`) over a **fixed 1m time series** of the same symbol/`price_source`, built from the same `TradeEvent`s. Never the renko series.                                                                                                                                                                                                                                              |
| (b) Cadence       | **Frozen at series construction**: brick size = `max(1, ATR_last_closed_1m_bar_before_series_start * mult)` in integer ticks, resolved once. No per-brick or per-minute recompute. A different RESOLVED size is a new series (new `spec_hash`, because `range_ticks` differs).                                                                                                                         |
| (c) BI-4 / BI-5   | Hold, because the resolved size is a plain integer in the spec and a pure function of the (recorded) lookback trades; the builder never sees ATR. A drifting live ATR fails BI-5 whenever history is not replayed (verified, below).                                                                                                                                                                   |
| (d) Fields        | **No new `BarSpec` fields and no `SPEC_HASH_VERSION` bump.** The request type `RenkoAtrRequest` carries `period` (2..100), `mult_x100` (default 100), `source_interval_ms` (default 60000); the service resolves it to a normal renko `BarSpec` whose only sizing field is the integer `range_ticks`. Only `range_ticks` is hashed; the request and its provenance are not (see R2 spec design below). |
| Warmup            | Fewer than `period + 1` closed 1m bars before the start -> 422 (never a default size).                                                                                                                                                                                                                                                                                                                 |

**R2 spec design (request spec vs resolved spec).** `24-internal` §3.1's `_exactly_one` (merged in E12-T01, `bars/models.py`, renko reuses `range_ticks`) stays true for every
**resolved** `BarSpec` (what builders, `spec_hash`, storage and snapshots use): a renko spec has exactly one sizing
field, `range_ticks`, always set. The ATR request is a separate type, `RenkoAtrRequest(period, mult_x100,
source_interval_ms)`, validated at the API edge, which the bars service resolves into a normal `BarSpec` plus a
non-hashed **provenance record** (`resolved_from`: request, lookback end timestamp, source ATR value). So
`range_ticks` is never "server-filled alongside" `renko_atr_*`; builders and the validator never see ATR and the
validator is unchanged. The `renko_atr_*` names in row (d) are the fields of `RenkoAtrRequest`, **not** new
`BarSpec` fields.

- **`spec_hash` (canonical JSON).** As merged in E12-T01 (`bars/spec.py`, `SPEC_HASH_VERSION = 1`),
  canonical JSON includes **every** `BarSpec` field with defaults explicit, so adding any field to `BarSpec`
  would move every existing hash. This is a second reason ATR lives in `RenkoAtrRequest` and not in `BarSpec`:
  R2 needs **no** `BarSpec` field and **no** `SPEC_HASH_VERSION` bump. If a `BarSpec` field is ever added, it
  must either be omitted from canonical JSON when `None`/default (keeping `spec_hash_vectors.json` valid) or
  ship with a version bump and golden-vector update.
- **Clients cannot compute the resolved hash.** It depends on server-side lookback trades. The API must echo
  the resolved spec and `spec_hash` (and the request -> resolved mapping) in the response/subscribe ack; clients
  treat `spec_hash` as an opaque server-issued id. The bars service persists the mapping so a re-subscribe with
  the same request is idempotent.
- **A different ATR period/multiple yields a NEW series only if the RESOLVED brick size differs** (the hash
  covers `range_ticks`, not the request): two requests that resolve to the same integer share one `spec_hash` and
  one series; a re-resolution at a later time that lands on a different integer is a new `spec_hash`. The old
  series is never mutated.
- **Anchor/tie-break.** "Last closed 1m bar before series start": a 1m bar whose close boundary is
  `<= start_ts` is closed (a start exactly on a boundary uses the bar that just ended, not the one beginning).

**BI-5 and `restore()`.** `BuilderState` (§3.2) MUST persist the resolved brick size in **price units** and the
`spec_hash` it belongs to (proposed fields `resolved_brick_px`, `tick_size_at_start`, `spec_hash`). `restore()`
reads these and **never re-resolves** ATR; a restore whose persisted `spec_hash` differs from the requested one
is refused, not silently re-keyed, and a restore is also refused when the instrument's CURRENT tick size differs
from `tick_size_at_start` (see the epoch rule below). Without this, a restart after a
long gap would resolve a different size, create a new `spec_hash` and make BI-5 only nominally true.

**Mid-session tick-size change (applies to R1 fixed renko and range bars too).** §3.3 defines a brick as
`range_ticks x tick_size`, but `tick_size` is **not** a `BarSpec` field (merged `bars/spec.py`), so the same fixed
spec hashes identically before and after an exchange tick-size change and a "new `spec_hash`" cannot happen. Rule
(option a, no hash change, no `SPEC_HASH_VERSION` bump):

- The **`spec_hash` is unchanged**; the series gains an **epoch** keyed by the tick size at construction.
  `BuilderState.tick_size_at_start` (from the instrument-info cache, `21-database-schema.md`, refreshed every
  12 h) is captured when the series starts, and the brick/range size is frozen in price units
  (`range_ticks x tick_size_at_start`) for the life of that epoch, so BI-4/BI-5 never depend on cache timing.
- `restore()` refuses (a typed error, not a silent re-key) when the instrument's current tick size differs from
  the snapshot's `tick_size_at_start`; the service then starts a **new epoch** (index restarts, new generation) under
  the same `spec_hash`. Bars carry/are keyed by `(spec_hash, epoch)`; the epoch id is part of the
  generation/pointer key below.
- The UI shows a notice on epoch change ("Tick size changed; series restarted"). The old epoch stays readable
  and is never mutated.
- Rejected alternative (b): add a tick-size `BarSpec` field with a `SPEC_HASH_VERSION` bump and new golden
  vectors; it moves every existing hash for an event that is rare and instrument-scoped.

**Security note (E12-T05): the R1 integer pattern and the R2 `atr:<2..100>(:<mult>)?` pattern are whitelisted
regexes with bounded length (`maxLength: 24` already), not a parser.

Evidence (seeded, 400k trades, `atr_experiment`): frozen brick 176 ticks, 301 bricks, BI-4/BI-5 hold over 10
random cuts; live-drifting ATR resumed from a restart without history reproduces **a different series**
(BI-5 false).

## Decision 2 — Rebuild: chunked pull in a bounded worker with a cancellation token, generation-swap publish

Cancellation contract for E12-S12 (`rebuild(spec, range, token) -> RebuildResult`):

1. Rows are read in chunks (<= 8 192 rows) in a worker thread; the token (a `threading.Event`) is checked
   between chunks **and** every <= 4 096 rows of building.
2. **Publish by generation swap, not "one commit".** QuestDB (ADR-0003 hot tier) has no multi-row atomic
   commit. The rebuild writes all rows under a new **series generation id**, then flips a per-`(symbol,
spec_hash)` **current-generation pointer** (one transactional Postgres row update) as its only publish step.
   Readers resolve the pointer first and **pin** that generation for the whole read, so two generations are never
   mixed. The superseded generation is garbage collected only when its **reader lease/refcount reaches zero**: every reader
   (including a replay session, which can hold a generation far longer than one read timeout) takes a lease on the
   generation it pinned and renews or releases it, and a lease that is not renewed within a TTL expires so a
   crashed reader cannot block GC forever; a
   failed or cancelled generation is deleted immediately. Cancel leaves no _visible_ rows (the pointer never
   moved) and orphans are swept. Schema detail belongs to the E12-T02/S12 contract-first PR; this is the
   semantic requirement.
3. **Staging bound.** Closed bars stream to the write-behind in batches; nothing holds a whole series. Where a
   buffer is unavoidable the cap is **250 000 bars per rebuild**; exceeding it fails the rebuild with a typed
   error (`bar_rebuild_too_large`, 422; copy: "Too many bars for this setting; choose a larger size").
   Sizing: prototype tuple bars cost roughly 0.45 KB each (peak RSS 106 MB for 51 024 volume bars vs 83 MB for
   1 440 time bars, so ~23 MB; coarse); a production `Bar` with `Decimal`s and pydantic is **estimated** at
   1.5-3 KB (unmeasured), so the cap is about 0.4-0.75 GB worst case, and an uncapped 1M-bar spec (1-lot
   volume bars) would be 1.5-3 GB, hence cap and refuse.
4. `asyncio.Task.cancel()` alone is **not** the mechanism: it only abandons the `await`.
5. **Executor (C-2.18).** Rebuilds run on a **dedicated bounded** `ThreadPoolExecutor` (proposal: 2 workers)
   with a bounded admission queue (proposal: 4 waiting). When full the request is **refused**
   (`bar_rebuild_busy`), never queued unboundedly and never on the default `to_thread` pool the rest of the
   app shares. (The harness used `to_thread` for brevity.)
6. **Same code as live/replay (C-2.15).** Rebuild drives the production builder through the same `BarBuilder`
   code and the same `spec_hash`; there is no fast path. A rebuild MUST NOT swap the pointer for a
   `(symbol, spec_hash)` while a replay session is reading it: replay pins its generation, the swap is deferred
   until the session ends, or the rebuild is refused with `bar_rebuild_busy`.

**Cancel path contract (PROPOSAL for the contract-first PR; not authoritative until it lands in 22-api/23-ws).**

- REST: `POST /v1/market/bars/rebuilds` returns `{rebuild_id, spec_hash, generation}`;
  `DELETE /v1/market/bars/rebuilds/{rebuild_id}` returns 202, idempotent, 404 if unknown.
- WS: client frame `{"op": "bars.rebuild.cancel", "rebuild_id": "..."}`; server frames
  `bars.rebuild.progress|done|cancelled`.
- **Owner:** the `bars` service holds the registry `rebuild_id -> (threading.Event, task, generation, owner
principal)`. RBAC applies (C-12.4): only the requesting principal (or Owner) may cancel.
- **Client disconnect cancels** the rebuild it started (WS close or REST request abort). Background rebuild
  jobs that outlive a client are out of scope for R1.
- **Client ingestion (26-chart-engine).** A rebuilt series arrives as a snapshot carrying the new `generation`;
  the client does a **full replace** of the series in the DataModel, never a merge with bars of the old
  generation.

Metrics (E12-S12 ships them from day one): `bar_rebuild_duration_seconds{kind}`,
`bar_rebuild_cancelled_total{kind}`, `bar_rebuild_rows_total{kind}`, `bar_rebuild_cancel_latency_seconds`.

## Measurements

Hardware: Intel64 Family 6 Model 142 (8 logical CPUs), 15.9 GiB, Windows 11, CPython 3.12.3, single process,
no other deliberate load. **Not the 4 vCPU / 8 GB reference VPS**; absolute numbers are indicative.

**Data source (important):** no QuestDB is reachable here (no docker, nothing on :8812), so the read path was
**not** measured against QuestDB. Input is a **synthetic-from-corpus** 1M-trade day (seed 12001): the empirical
qty/side/price-step distributions of the recorded BTCUSDT frames (`packages/fixtures/bybit/2026-10-05`) are
bootstrapped into a random walk, stored as zstd Parquet (8.0 MB) and read via pyarrow in 65 536-row batches
(the cold-path stand-in). Builders are the throwaway prototypes in `bench/renko_rebuild/builders.py`, using
plain ints; they are not the E12-S0x builders (those do not exist yet), so production builders emitting
`Decimal` pydantic bars will be slower — see the follow-up.

Rebuild of 1M trades (median of 5, each in a fresh subprocess; wall includes Parquet read). **Quiet-machine
baseline; the loaded round-3 re-run is in the "Round-3 re-run" note below the cancellation table:**

| Builder             | Bars out | Wall (s) | Rows/s | Peak RSS (MB) | Read (s) | vs 10 s |
| ------------------- | -------- | -------- | ------ | ------------- | -------- | ------- |
| time (1 m)          | 1 440    | 0.91     | 1.10 M | 83            | 0.036    | pass    |
| tick (1 000)        | 1 000    | 0.82     | 1.21 M | 84            | 0.036    | pass    |
| volume (5 000 lots) | 51 024   | 1.02     | 0.98 M | 106           | 0.036    | pass    |
| range (20 ticks)    | 17 108   | 0.89     | 1.12 M | 91            | 0.038    | pass    |
| delta (2 000 lots)  | 19 188   | 0.92     | 1.09 M | 92            | 0.037    | pass    |
| renko (10 ticks)    | 40 467   | 1.05     | 0.95 M | 98            | 0.037    | pass    |

All six pass with ~10x headroom; **dominant cost is per-trade Python overhead (~96 %)**, not the read (3.5 %)
or the emit. All six in one pass (`BarBuilderSet`) is roughly 5.5 s of summed build time, still < 10 s. Caveat: a proxy for
the PGWire path (materialising 1M Python row dicts + `pa.Table.from_pylist`) cost 0.80 s + 0.68 s on this
machine, i.e. roughly doubling the read side, so the QuestDB path is expected to remain inside 10 s but **this
is unmeasured** and must be re-run when QuestDB is available (follow-up).

Cancellation (**quiet-machine baseline**, see the round-3 note below for the loaded re-run; renko rebuild, cancel
fired at 15-60 % of a ~1.0 s run, 20 trials per row; latency from the intended cancel instant to "stopped and
released"):

| Strategy                                                         | Chunk rows | p50 (ms) | max (ms) | Rows leaked after cancel | 250 ms   |
| ---------------------------------------------------------------- | ---------- | -------- | -------- | ------------------------ | -------- |
| A. `task.cancel()`, builder on the event loop, `await` per chunk | 8 192      | 7.6      | 28.2     | 0                        | pass     |
| A. same                                                          | 65 536     | 150.3    | 188.6    | 0                        | marginal |
| A. same                                                          | 262 144    | 729.0    | 794.1    | 0                        | **fail** |
| A2. `task.cancel()` over `to_thread`                             | 65 536     | 670.3    | 1 062.8  | 809 340 (zombie commits) | **fail** |
| **B. token, chunked pull in thread**                             | 8 192      | 2.2      | 4.5      | 0                        | pass     |
| **B. same**                                                      | 65 536     | 5.8      | 8.8      | 0                        | pass     |
| **B. same**                                                      | 262 144    | 5.5      | 12.8     | 0                        | pass     |

A works only for tiny chunks and stalls the loop for the whole chunk (150 ms at 65 536 rows violates C-2.18's
no-blocking rule). A2 is the trap: the caller sees "cancelled" but the thread keeps running and later commits.
B is chunk-size-insensitive because the token is also polled inside the batch. The PGWire cursor-close
behaviour (does `asyncpg` abort a server-side query promptly?) is **not measured**; B does not depend on it
since it bounds the work per page and closes between pages.

**Round-3 re-run (harness only changed: cancel prototypes now start tasks via `spawn`, semantics unchanged).**
The machine was busier (baseline renko rebuild 1.28 s vs 1.04 s), so absolute times drifted up, with the same
ordering and pass/fail: A 8 192 rows p50 11.4 ms (max 49); A 65 536 p50 190 ms (max 245); A 262 144 p50 1 101 ms
(**fail**); A2 p50 918 ms with the same 809 340 leaked rows (**fail**); B p50 5.7 / 11.6 / 8.5 ms at 8 192 /
65 536 / 262 144 rows (max 54, pass). Builders re-ran at 0.97-1.61 s each (all pass). The tables above are the
original quiet-machine run; none of the conclusions change, but tail latency is load-sensitive, so E12-T07
must assert cancel p95 under load, not only on an idle host.

Invariants on the prototypes (50k trades, 20 random cut points each): BI-1, BI-4, BI-5 true for all six.

## Consequences

- E12-S04 builds fixed-size Renko only; param parsing is the integer whitelist; `atr:*` is a 422.
- E12-S12's rebuild API takes a token and publishes by generation swap; no reliance on task cancellation.
- **E12-T07 is the BLOCKING re-measurement gate** for the 10 s NFR: 1M prints through the production
  `Decimal`/pydantic builders, the E08 QuestDB PGWire read path, on the reference 4 vCPU / 8 GB VPS. This ADR's
  numbers do not satisfy US-CHART-003 on their own. The single-pass all-six figure (~5.5 s of build time here)
  would breach 10 s at a mere 2x slowdown, and Decimal/pydantic builders could plausibly cost 10-30x (estimate,
  unmeasured), so the headroom is **not** assumed to survive.
- Descoping note for `30-release-roadmap.md` §12 rung 2 (Renko and range bars -> R2): at risk is **only** the
  builder + UI of two cheap builders (both ~0.9-1.0 s / 1M rows, no new storage); `bars_range`/`bars_renko`
  tables already exist. ATR bricks are already out of R1 by this ADR, so pulling the rung removes no ATR work.
  Cutting rung 2 saves roughly the E12-S03/S04 effort and nothing in the rebuild/cancel path (shared).
- New risk to log in `32-risk-register.md` (not edited here; governed): "rebuild budget unmeasured on QuestDB
  PGWire and on production (Decimal/pydantic) builders".

## Rejected

- ATR over the renko series (circular). Live/per-brick ATR (fails BI-5 without full-history replay). Ship
  `atr:14` in R1 (three new contract surfaces on a cuttable feature). `Task.cancel()` as the sole mechanism.

## Revisit when

Not a soft trigger: E12-T07 (above) is a blocking gate. If any builder exceeds 10 s there, the dominant cost
is recorded and an optimisation Task is filed (batch/columnar builders) rather than relaxing the NFR.

## Follow-ups

Filed after owner ratification, so they carry the final decision (checklist on #525): E12-S04 (integer renko, param
whitelist, 422 copy, tick-size epoch rule; ATR R2 as a later ticket), E12-S12 (rebuild API, cancel contract, token
registry, generation swap with reader leases, bounded executor, metrics), the contract-first PR
(`docs(protocol)!:`), and a `32-risk-register.md` entry. The QuestDB-path re-measure is **folded into E12-T07**,
whose gate scope is: production `Decimal` builders, E08 PGWire read path **including cursor release**, reference VPS,
and cancel p95 <= 250 ms **under load**.

## Addendum 1 — 2026-11-03: rebuild and invalidation as built (E12-K02, #526)

_Status: records the state of `main` at `c6b53ad9d`; the Decision 2 text above is unchanged and still
binds E12-S12. E12-S12 (#535) adds Addendum 2 when the rebuild ships. The consumer view is
`docs/plan/36-bar-semantics-reference.md` §5 and §7._

**Built.**

- `generation` is part of every stored bar's key (`(ts, symbol, bar_param, generation, index)`, QuestDB
  migration 0004) and of both wires; `index` restarts only inside a fresh generation.
- Decision 1's epoch rule maps onto `generation`: there is no separate epoch column. A builder cold
  start begins a new generation above any this process or a discarded state blob recorded, and older
  generations stay readable beside it, so a read may span several. A tick-size change refuses the
  renko state and starts a new epoch the same way.
- A generation change reaches WS subscribers as a full snapshot (`meta.reason: "generation_swap"`),
  never a delta, and clients replace the series; this is the "client ingestion" rule of Decision 2.
- `build_version` is recorded per row (all six families at version 1). Reads serve rows below the
  running version as stored, count them (`bars_stale_build_version_total`) and request a rebuild
  (`bars_rebuild_scheduled_total`).
- A closed bar that is not stored is recorded as a coverage hole, served in `meta.coverage_holes` and
  queued for heal (#5432); nothing consumes that queue until the rebuild executor exists.

**Not built (pending E12-S12, #535; #1997 job, #2127 contract-first).**

- No rebuild executor runs: a requested rebuild is logged (`bars_rebuild_unexecuted`) and older-version
  rows are **not healed**.
- No current-generation pointer, no swap, no reader leases on a generation and no generation GC.
  (The series spec leases of E12-T03 are a different mechanism: reference counts on a live series.)
  Reads therefore return every stored generation in the window rather than one pinned generation.
- No cancellation token, bounded rebuild executor, 250 000-bar staging cap, `bar_rebuild_busy` /
  `bar_rebuild_too_large` errors, rebuild REST/WS shapes or `bar_rebuild_*` metrics.
- The replay rule of Decision 2 point 6 is therefore satisfied vacuously today: nothing can swap a
  generation under a replay session. It becomes an obligation on E12-S12.

**Measured since the decision.** The E12-T04 harness measured the production `Decimal` builders at
25 471 to 35 449 prints/s (28 to 39 s per 1M prints, developer laptop,
`services/api/bench/bar_determinism/baseline.json`), against about 1M/s for the prototypes above. The
10 s NFR fails on the production path (#2167, RSK-062), which this ADR's Consequences anticipated. The
E12-T07 gate and E12-Q05 (#528) reference-host numbers are still pending; until they land, the prototype
tables above are prototype figures, not production expectations.

**Alternatives still rejected.** `Task.cancel()` as the sole cancel mechanism, a single multi-row
"commit" publish (QuestDB has none), and an unbounded staging buffer: nothing built since changes the
reasons above.
