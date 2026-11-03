# ADR-0045 — Drawing persistence model and chart-space geometry contract (E14-C01)

- Status: **proposed (gated)** (2026-11-03; deadline: E14 epic close). Built on the BQ defaults; rulings pending
  (#540 comment 6610606584, BQ-01 to BQ-10). **Binding now:** the server-side clauses, which record what E14-T01
  (#357, closed) shipped: Decisions 1, 2, 3 (the tool list and its rules), 8, the server bullets of Decisions 4 to 7
  and the server values of Decision 9. **Gated:** the clauses marked _client_, taken from PR-A of E14-T02 (#5481,
  open, head `da6ae62e747febe8d78523e5100fdbec526bfd29`) and re-checked against PR-B; Decision 10, which E14-T03 and
  E14-T04 still have to build; and any clause a BQ ruling changes. The Validation gate says how each is settled.
- Date: 2026-11-03
- Deciders: Owner (`@basiltt`) and Architect; the Security engineer for the audit-posture clause (Decision 8) and
  the E14 lead, per the ticket's Test plan. Author: hpe-worker-1.
- Numbering note: the ticket (E14-C01, #540) says "ADR-0014". 0014 is taken (observability) and is cited from
  `22-api-openapi.yaml`, `23-ws-protocol.md` and `spikes/E04-K01.md`; 0031 is reserved by E45-K01; 0041 is held by
  open PR #5474; 0042 and 0043 are claimed by #1085 (its BQ-1); 0044 by #1029. This record takes 0045, as the
  coordinator ruled on the BQ comment. If any of those numbers is released, 0045 stays: a gap costs nothing, a
  collision does.
- Consulted: `docs/security/threat-models/E14-drawings.md` (DR1, DR16, DR17, DR18, DR24, DR33, DR42; §4 limits);
  `docs/design/E14/E14-D02.md`; the #357 decision record; the #400 BQ rulings (BQ-T02-04).
- Related: E14-T01 (#357), E14-T02 (#400), E14-T03 (#358), E14-X01 (#433), E14-Q05 (#468), E14-Q06 (#469), #3055
  (the stale "until layouts ship" text); ADR-0002 (engine), ADR-0005 (WS protocol), ADR-0033 (renko and range bars).
  Informs E15, E26, E40 and E41.
- Evidence: every `file:line` holds on `main` at `b81479ab01109ee1efc6cdedb411bd5f75ecdd66` unless it names #5481.
  Server paths are under `services/api/candleviewer/`; `models` is `api/drawings_models.py`, `router` is
  `api/drawings.py`, `repo` is `storage/repositories/drawings.py`; `NN:line` is a line of `docs/plan/NN-*.md`;
  `TM` is the E14 threat model; client paths are under `apps/web/src/features/drawings/store/` on #5481.

## Context and problem statement

E14 makes decisions that every later epic inherits: E15 embeds drawings in `WorkspaceExport.drawings` (22:24798),
E26 renders stored anchors on a replayed timeline, E40 links a line to an alert through `drawings.alert_id`, and
E41 embeds notes in journal snapshots (US-DRAW-006). `21-database-schema.md` §3.8.3 states the table's shape
(21:3576-3611) and `22-api-openapi.yaml` states the API's shape (22:10594-10870), but neither says why geometry is
chart-space JSONB, why writes are batched and optimistic, what happens when two sessions edit one drawing, or what
the scope columns mean for sync.

T01 and PR-A of T02 have since answered most of these questions in code. This record writes those answers down as
decisions, with alternatives and consequences, so a later epic cites them instead of re-deciding them. Where the
code differs from the ticket's scope list, the code is recorded and the difference is named: the tool count (25,
not 24), the conflict policy (optimistic concurrency, not last-write-wins), the anchor precision (milliseconds, not
microseconds) and undo of a delete (a new id, not a restored row).

## Decision drivers

- Anchors must survive zoom, scale mode, DPI, interval and bar-type changes (E14 epic AC "Anchors are chart-space,
  not pixels"; 26:331, 26:831).
- Prices are never floats on any path that stores or compares them (the ticket's Technical notes).
- One owner, a few devices, low write rate: proportionate concurrency, no collaborative merge (US-DRAW-009 NFR,
  11:1336; multi-user drawings are R5, out of scope).
- The WS protocol carries market and account data and is frozen for additive change only (ADR-0005; C-6.3).
- Size and quota limits live in one reviewed place (TM §4), and this record must not weaken a TM control.
- Single source per fact (C-16.5): this record cites the TM, the contract and the code rather than restating them.

## Considered options

Per decision; the rejected ones and the reasons are under "Why not the alternatives".

1. Geometry storage: **chart-space JSONB** (chosen); a normalised `drawing_points` table; bar-index anchors; pixels.
2. Anchor encoding: **ISO UTC ms string + decimal string** (chosen); µs integers; µs ISO strings; float prices.
3. Per-tool shape: **one closed generic shape plus per-tool rules** (chosen); one OpenAPI schema per tool; free-form.
4. Write path: **optimistic store, debounced atomic batches** (chosen); per-edit PUT; WS mutation; explicit save.
5. Concurrency: **optimistic concurrency on the `updated_at` token, server wins** (chosen); pure last-write-wins;
   an integer `version` column; CRDT merge.
6. Scope and sync: **`layout_id` scope, REST-only sync** (chosen); expose `interval_scope`; a WS invalidation topic.
7. Lifecycle: **soft delete, 90-day purge, undo re-creates** (chosen); hard delete; a restore endpoint.
8. Audit posture: **outside C-2.9, denials audited** (chosen, by E14-X01); every write audited; nothing audited.
9. Limits: **as-built table, negotiable** (chosen); wait for E14-Q05; no caps.
10. Projection: **exact instants, engine-side projection** (chosen); snap anchors to bars on write; store per interval.

## Decision outcome

### Decision 1 — geometry is chart-space JSONB (frozen)

A drawing's `geometry` is a JSONB object holding `points: [{t, p}]` plus the tool's extras, enforced by the
`dr_geom` CHECK (21:3607). It never holds pixels and never holds bar indices. The two range columns `anchor_start`
and `anchor_end` are the earliest and latest point times, derived on every write (`models:227-231`, `models:400-431`)
and indexed by `ix_dr_range` (21:3610). The per-chart load is `WHERE owner_user_id = $1 AND symbol = $2` on the
partial index `ix_dr_user_symbol` (21:3609), budget 28, under 5 ms (21:5615). That index is a documented dependency
of this decision, not an incidental one: geometry is opaque to SQL, so every query reads the scalar columns.

### Decision 2 — the anchor format (frozen; BQ-04)

- `t` is an RFC 3339 UTC instant with `Z`, 0 to 3 fraction digits (at most millisecond precision), years 2000 to
  2099, calendar-checked (`models:192-195`, `models:199-224`; 22:23295-23303).
- `p` is a decimal string: optional `-`, at most 15 integer digits and 12 fraction digits (`models:196`;
  22:23304-23308).
- Both are stored as the strings the client sent and returned verbatim; `p` is never converted to a float on the
  server (`models:407`, `models:8-9`). A tick-rounded price round-trips exactly.
- `p` may be negative. The measure and price-range tools can be dragged below zero on an autoscaled pane, and a
  derived or spread series is a future possibility; refusing a negative price would make the store, not the engine,
  decide what the chart may show. The engine's log guard already falls back to linear for a non-positive value
  (26:784).
- Millisecond precision matches the exchange's millisecond timestamps and whole-millisecond bar times; finer
  precision has no consumer.
- Non-price extras are JSON numbers, because they are ratios and counts, not prices: `levels` in [-1000, 1000] with a
  1e-6 magnitude floor (`models:233-250`, `models:262-322`), `bands` from 1 to 3, the `extend_*` booleans. **Any
  future price-valued extra must be a decimal string**, like `p`.

Frozen: chart-space, decimal-string price, UTC instant, no pixels or indices. Widening `t` to microsecond ISO is not
plainly additive: readers rely on the pattern, so it needs a C-6.3 review and is treated as breaking unless readers
are shown tolerant. Narrowing either pattern is a breaking change.

### Decision 3 — 25 tools, one closed shape, per-tool rules (frozen list; additive growth)

The tool enum has **25** values, one list shared by the `Tool` Literal (`models:40-68`), the `dr_tool` CHECK
(21:3600-3606) and the OpenAPI `DrawingTool` enum, which readers must treat as open-ended (22:23249-23253). The
ticket's "24" is stale. The geometry shape is one closed model (`models:262-322`, `extra="forbid"`), and the rules
that depend on the tool run in one cross-field validator (`models:378-398`):

- point counts per tool from `POINT_COUNTS` (`models:70-104`; 22:23255-23262): 1 for `horizontal_line`,
  `vertical_line`, `text`, `anchored_vwap`; 3 for `parallel_channel`, `triangle`, `fib_extension`, `pitchfork`,
  `long_position`, `short_position`; 2 to 500 for `brush`, 2 to 100 for `polyline`; 2 for the other 13;
- `text` is required for `text` and `callout` and refused elsewhere; `levels` only for the three fib tools; `bands`
  only for `anchored_vwap` (`models:111-113`).

Two corrections to the ticket's list. **There is no channel-width field**: `parallel_channel`'s third point sets the
width (the offset of the second rail through it), as E14-D02 draws it (`E14-D02.md:45`, T25 at :243). **The position
tool's entry, stop and target are its three points**, in placement order entry → stop → target (E14-D06 AD-11,
`E14-D06.md:58`); there is no separate field for any of them. A risk size computed from a manipulated `geometry` is
TM DR16 (High, owned by E14-S07, unbuilt); this record adds no control for it and removes none. Per-tool
tables (point counts, option fields, bounds) are in `24-internal-schemas.md` §1.7 (this ticket's second slice, BQ-07),
checked against these constants and `22` by `test_drawing_tool_schemas_contract.py`. Server validation of all 25 is
shipped (#357); the client's R1 tool set belongs to E14-S04 to S06.

### Decision 4 — optimistic store, debounced atomic batches (debounce negotiable)

- _Client._ Local edits apply at once; mutations coalesce per id and flush on a **500 ms trailing debounce capped by
  a 2 s maxWait**, or at once on `flush()` (pointer-up, tool change, pane close), with **one request in flight**
  because each `if_match` chains on the previous answer (#5481 `drawingSync.ts:1-5`, `:22-23`, `:139`). Retries
  re-send the same body under the same `Idempotency-Key` with full-jitter backoff (`drawingSync.ts:6-7`; TM DR33).
- _Server._ `POST /drawings/batch` takes 1 to 200 operations and applies them in order in **one transaction**; the
  first operation that cannot apply rolls the whole batch back with `409 conflict` and
  `errors[0] = {field: "operations.<i>", rule}` (22:10730-10760; `router:619-659`). Only three rules answer that
  way: `target_unavailable`, `version_conflict` and `id_unavailable`. A batch `layout_not_found` and an
  `immutable_field` answer `422 validation_failed` (`router:637-638`, `router:646-648`), and a quota breach
  `409 drawings_quota_exceeded` (`router:639-640`); every one of them rolls the whole batch back. `POST` and batch
  replay an `Idempotency-Key` from a bounded per-user cache (`router:11-12`; TM §4).

### Decision 5 — optimistic concurrency on the `updated_at` token, server wins (BQ-03; negotiable)

The ticket's scope item 4 asked for last-write-wins on `updated_at`. As built, the policy is optimistic concurrency:

- the concurrency token is the row's `updated_at`, serialised with exactly six fraction digits and `Z`
  (`repo:126-128`); every write moves it strictly forward, `greatest(clock_timestamp(), updated_at + 1 µs)`
  (`storage/repositories/drawings_sqlalchemy.py:118`), so two writes never share a token;
- a batch `update` or `delete` **requires** `if_match` in that exact spelling (`models:440-489`); a stale token
  rolls the batch back with `409 conflict`, rule `version_conflict` (22:10742-10749; `router:129-133`);
- `PUT /drawings/{id}` takes an **optional** `If-Match`: stale or unparseable gives `412 version_conflict`, absent
  gives last-write-wins (22:10822-10825; `router:353-367`, `router:586-601`);
- _client:_ the first-party client always sends the token. On `version_conflict` it re-reads the symbol, confirms
  silently a row that already equals what it sent, and otherwise **adopts the server version**, tags the drawing
  "changed elsewhere" (or removes it, "removed elsewhere") and announces it once per episode (#5481
  `drawingSync.ts:339-372`; E14-D02 :283, :501, :538). Re-applying the local version is one undoable command.

Two paths are not optimistic. A token-less `PUT` is last-write-wins, and the single `DELETE /drawings/{id}` takes no
precondition at all (`router:608-617`; 22:10856); no first-party client sends either: the store writes through the
batch. This is the ticket's AC "implementation diverges from the ADR": the divergence is recorded here and on the
E14 epic, and **E14-Q06 scenarios 7 to 9 must assert `version_conflict` with server-wins and the one-time notice,
not last-write-wins**.
Making `If-Match` mandatory on `PUT` is a possible later contract change, not taken here.

### Decision 6 — scope and sync: `layout_id`, per symbol, REST only (BQ-06)

- `layout_id` NULL means symbol-global: the drawing shows in every pane on that symbol. Non-NULL means pane-local, and
  the layout must be one of the caller's live layouts, checked in the write's transaction (422 `layout_not_found`;
  `router:18-23`) and backed by a same-owner composite FK (`migrations/versions/0022_workspaces.py:15-26`).
- `interval_scope` stays **NULL-only and unexposed** in R1 (21:3592; E14-D02 :91): a drawing shows on every interval.
- Sync is per layout and per symbol and never crosses symbols (US-DRAW-009 NFR, 11:1336). Panes in one client share
  the in-memory store per symbol, and one undo history per symbol (#5481 `history.ts:1-2`).
- **Across tabs and devices, sync is REST only.** `23-ws-protocol.md` has no drawing topic and gets none. _Client:_
  the store re-reads a symbol on mount, after any `409`, and, PROPOSED, on `visibilitychange` when its last read is
  older than 60 s (#400 BQ list; PR-B, not on #5481 yet).
- RBAC: `workspaces:read` to list, `workspaces:write` to write, scope self; the owner always comes from the session
  (`router:3-6`; TM DR1; C-12.4).

### Decision 7 — lifecycle: soft delete, 90-day purge, undo re-creates (frozen soft delete)

- Delete sets `deleted_at`; the row is hard-purged after **90 days** (`storage/retention/policy.py:124-125`;
  21:4974). Until the purge, its id is unavailable to any new create (`id_unavailable`, 22:10750-10751).
- _Client:_ **undo of a delete re-creates the drawing under a new id with identical content**; the soft-deleted row is
  never restored, and there is no restore endpoint (#5481 `history.ts:3-4`). An undo whose target was removed
  elsewhere is dropped and reported, never resurrected (`history.ts:5`); this is the answer to E14-Q06 scenario 12's
  restore race. The ticket's "undo operating on the soft-deleted row" is superseded by this as-built rule.
- **Cascade from layouts.** Soft-deleting a layout, or a workspace with its layouts, soft-deletes the pane-local
  drawings on it in the same transaction and moves their token (`storage/repositories/workspaces_sqlalchemy.py:129-134`,
  used at :454 and :537). A layout is purged only once no live drawing hangs below it (`_PURGE_LAYOUTS`, :252-258),
  and the purge then removes its soft-deleted drawings through the FK's `ON DELETE CASCADE`
  (`migrations/versions/0022_workspaces.py:142-144`). _Client:_ an undo of such a drawing re-creates it with a dead
  `layout_id`, which fails `422 layout_not_found`; a `422` is never re-sent, the symbol is re-read and server truth
  adopted (#5481 `drawingSync.ts:7-8`), so the trader sees the drawing removed elsewhere.
- `alert_id` is `ON DELETE SET NULL` and not exposed (21:3596). E40 owns what a drawing's soft delete does to its
  alert; until then a soft-deleted drawing keeps its link and its alert is unaffected.

### Decision 8 — audit posture (cites #357 and E14-X01; adds nothing)

Drawing writes are **outside** the C-2.9 append-only audit scope: decided on #357 (decision record 11), recorded by
E14-X01 as TM DR17 (TM:138), and stated in the router (`router:10`). Permission denials are audited as
`rbac.denied`, and so are foreign-id probes on `PUT`/`DELETE` and the failing operation of a batch whose target is
foreign or missing (TM DR18, DR24; `router:14-16`, `router:651-654`). A new mutating route is fenced by the Semgrep
`audit-write-required` rule (TM DR42). This record weakens no TM control.

### Decision 9 — limits and quotas (values negotiable; BQ-08)

| Limit                               | As-built value                                         | Source                             |
| ----------------------------------- | ------------------------------------------------------ | ---------------------------------- |
| Live drawings per symbol / per user | 500 / 5 000, past either `409 drawings_quota_exceeded` | `repo:25-27`; TM:109               |
| Operations per batch                | 200                                                    | `models:106`; 22:10739             |
| Body: single / batch                | 64 KiB / 1 MiB, `413` before parse                     | `models:107-108`; TM §4            |
| JSON depth                          | 16                                                     | `models:109`                       |
| `geometry.text` / `label`           | 1 000 / 120 code points, raw length first              | `models:114-115`, `models:150-170` |
| Points: `brush` / `polyline`        | 500 / 100                                              | `models:102-103`                   |
| `levels` / `bands`                  | ≤ 24 / ≤ 3                                             | `models:311`, `models:319`         |
| Writes per user                     | 60 a minute, burst 20, past it `429`                   | TM:110                             |
| Idempotency cache                   | the TM §4 row                                          | TM §4                              |
| _Client_ debounce / maxWait / chunk | 500 ms / 2 s / 200 operations                          | #5481 `drawingSync.ts:22-24`       |

The basis today is the E14-X01 review values, not a measurement: E14-Q05 (#468) is open. The Validation gate
re-bases these numbers on E14-Q05's results at epic close; until then they are review defaults.

### Decision 10 — interval change, non-time bars and log scale (BQ-05)

- Anchors are exact instants and linear prices; **projection to the screen is the engine's job** (26:228). The
  engine-side model of 26 §3.10 also keeps a `barIndex` (26:330); the stored form is time only, and time wins.
- On an interval change an anchor renders at its exact time, inside the bar that contains it; it is never re-snapped
  and never rewritten. The store does not change when the interval does (E14-D02 T09 :227).
- On renko and range bars (ADR-0033), whose bars are not time-uniform, an anchor maps to the first bar whose time
  span contains `t`, at its exact price.
- On log scale only the anchors are projected (the float64 `projectRel`, which already serves drawings, 26:228;
  `packages/chart-engine/src/viewport/transform.ts:133-139`), and a segment is drawn straight in screen space between
  them, as T03's vertex shader re-projects `p0`/`p1` (#358 Technical notes). The stored geometry stays linear prices.
- These are decisions for E14-T03 and E14-T04 to build; no drawings layer is on `main` yet. They are named in the
  Validation gate.

### Accessibility

Every stored drawing must yield a deterministic accessible name from its stored fields alone: tool, anchor time(s),
price(s) and the optional `label`, as E14-D02's tree rows and surrogates compose it ("Trendline 13:40 → 14:05";
E14-D02 :327, :372) and as SCR-037 requires (14:977; `05-accessibility-standard.md` §6.1.1). No render state enters
the name, so the object tree (SCR-036) can name a drawing that is off-screen or hidden.

### Observability

The metrics that make these decisions falsifiable, checked in `observability/metrics_catalogue.py`:

| Decision              | Metric                                                               | State                      |
| --------------------- | -------------------------------------------------------------------- | -------------------------- |
| 4, 9 (batch size)     | `cv_drawings_batch_ops` (histogram)                                  | emitted (`:2761`)          |
| 5 (conflicts)         | `cv_drawings_conflicts_total{rule}`                                  | emitted (`:2772`)          |
| 9 (drawings per user) | `cv_drawings_rows_per_user{kind}`, `cv_drawings_rows{tool}`          | emitted (`:2805`, `:2794`) |
| 7 (purge)             | `cv_drawings_purged_total`                                           | emitted (`:2784`)          |
| 7 (soft-deleted rows) | a soft-deleted row count                                             | **not yet emitted**        |
| 9 (caps hit)          | `cv_drawings_payload_rejected_total`, `..._batch_cap_rejected_total` | emitted (`:2817`, `:2829`) |

A rising `version_conflict` rate says Decision 5's single-owner premise is wrong; a batch-size distribution pinned at
200 says the cap or the debounce is.

## Frozen and negotiable

| Frozen (changing it is a new ADR or a breaking change)       | Negotiable (tunable with evidence, by amendment)       |
| ------------------------------------------------------------ | ------------------------------------------------------ |
| Chart-space storage; no pixels, no bar indices (1)           | Debounce, maxWait and chunk size (4)                   |
| Decimal-string price; UTC instant; verbatim round-trip (2)   | Conflict policy details, e.g. mandatory `If-Match` (5) |
| The tool list only grows; readers tolerate unknown tools (3) | Every limit and quota in Decision 9                    |
| Soft delete with a retention purge (7)                       | The purge horizon (with the retention table)           |
| Atomic batch: all operations or none (4)                     | Cross-device refresh triggers (6)                      |

## Consequences

- **E15.** `WorkspaceExport.drawings` carries `DrawingInput`, which has no id (22:24798, 22:23369); an import re-mints
  ids, so an imported drawing never collides with a soft-deleted one. A pane-local drawing's `layout_id` must be
  remapped to the imported layout or the write fails `layout_not_found`. Deleting a layout or workspace soft-deletes
  its pane-local drawings with it (Decision 7), and an undo of the delete cannot bring them back to a deleted
  layout: E15's restore and undo flows must account for that.
- **E26.** Replay renders stored anchors read-only through the same projection (Decision 10); a replayed timeline
  needs no geometry migration.
- **E40.** `alert_id` is the only link; E40 decides the alert's fate when its drawing is soft-deleted.
- **E41.** A journal snapshot that embeds a note copies its fields; it does not reference a drawing id that may be
  purged after 90 days.
- Geometry is opaque to SQL: no query may filter on a point inside `geometry`; a new query shape needs a scalar
  column first.
- Validation is in the application layer only (Decision 3); the per-tool tables of slice 2 (24 §1.7) make it reviewable, and
  "server validation generated from the tables" is a direction, not built here.
- No WS contract change, no migration and no OpenAPI change come from this record.

## Why not the alternatives

1. **A normalised `drawing_points` table** is queryable per point, but nothing queries a point; it costs a join on
   every load (budget 28), and each tool's extras would need columns or a side table. **Bar-index anchors** break on
   every bar-type change and on history backfill. **Pixels** move on every zoom: rejected outright.
2. **µs integers** are a contract break and a geometry migration for no user-visible gain. **µs ISO** is additive
   but has no consumer. **Float prices** drift on round-trip and lose tick equality.
3. **One OpenAPI schema per tool** (a `oneOf` on `tool`) multiplies the contract by 25 and makes adding a tool a
   wider change; the closed shape plus `POINT_COUNTS` keeps one list. **Free-form geometry** fails TM §4.
4. **Per-edit `PUT`** is chatty during a drag and persists partial states. **WS mutation** puts low-rate config on
   a frozen market-data protocol (ADR-0005). **Explicit save** fails US-DRAW-001: levels must simply be there next
   session.
5. **Pure last-write-wins** silently clobbers another device's edit. **An integer `version` column** has the token's
   semantics plus a migration and a contract change. **CRDT merge** is disproportionate for one owner.
6. **Exposing `interval_scope`** needs a contract PR and no story asks for it. **A WS invalidation topic** needs a
   `23` contract PR, `make gen` and a server publisher for a low-rate surface where a focus re-read suffices.
7. **Hard delete** loses undo across a flush and the purge-window id guard. **A restore endpoint** adds a mutating
   route (DR42) for what a re-create already does.
8. **Auditing every write** puts presentation state into the C-2.9 log; **auditing nothing** loses the denial and
   probe trail DR18 and DR24 require. Both are E14-X01's to reopen, not this record's.
9. **Waiting for E14-Q05** blocks the record on a measurement that only re-bases numbers. **No caps** fails TM §4.
10. **Snapping anchors on write** loses the exact instant and breaks the next interval change. **Storing per
    interval** contradicts US-DRAW-009's cross-interval sync.

## Open questions

The rulings on BQ-01 to BQ-10 (#540 comment 6610606584) are pending; every default above is the BQ default. A ruling
that differs amends this record before it leaves `proposed`.

## Validation (epic-close gate, recorded on the E14 epic)

1. _Client clauses against E14-T02 PR-B:_ the 500 ms / 2 s debounce, one request in flight, server-wins on
   `version_conflict` with one notice per episode, undo-of-delete under a new id, and the mount / `409` /
   `visibilitychange` (> 60 s) re-reads. Any difference amends Decisions 4 to 7.
2. E14-Q06 scenarios 7 to 9 assert Decision 5 (`version_conflict`, server wins, one notice), not last-write-wins;
   scenario 12 asserts Decision 7's dropped undo.
3. Decision 9's values re-based on E14-Q05 (#468); the soft-deleted row count is emitted or its absence accepted.
4. Decision 10 checked against E14-T03 (#358) and E14-T04: an anchor keeps its time and price within one tick across
   log scale, an interval change and range bars (the E14 epic AC), and the 26:831 property test holds.
5. The slice-2 tables in `24-internal-schemas.md` §1.7 match `POINT_COUNTS`, `_TEXT_TOOLS`, `_LEVEL_TOOLS` and
   `_BAND_TOOLS`, and one fixture drawing per tool passes them.
6. The slice-3 cross-references cite this record and none contradicts it: 21 §3.8.3, the `/drawings` description in
   22, SCR-036 and SCR-037, including 14:976 ("≥2 anchors before it persists", which four one-point tools
   contradict), and a one-line pointer in 26 §3.10, whose engine model keeps a `barIndex` beside `time` (26:330).
7. Decisions 1 and 2: the verbatim round-trip tests stay green and cover `t` as well as `p`:
   `test_point_prices_round_trip_verbatim_through_db_values` (`tests/unit/api/test_drawings_request_models.py:220`)
   and `test_create_get_list_round_trip_keeps_decimals_verbatim`
   (`tests/integration/storage/test_drawings_repository.py:145`), both under `services/api/`.
8. Decision 8: the `audit-write-required` allow-list still holds exactly the three drawing routes (TM DR42).

## References

- Code: `api/drawings_models.py`, `api/drawings.py`, `storage/repositories/drawings.py`,
  `storage/repositories/drawings_sqlalchemy.py`, `storage/retention/policy.py`, `observability/metrics_catalogue.py`;
  #5481 `drawingSync.ts`, `history.ts`.
- Plan: 21 §3.8.3 and the retention table; 22 `/drawings*`, `DrawingTool`, `DrawingPoint`, `WorkspaceExport`;
  11 US-DRAW-001, US-DRAW-006, US-DRAW-009; 14 SCR-036, SCR-037; 26 §3.5, §3.10; `05-accessibility-standard.md`
  §6.1.1.
- Design and security: `docs/design/E14/E14-D02.md`, `docs/design/E14/E14-D06.md`,
  `docs/security/threat-models/E14-drawings.md`.
