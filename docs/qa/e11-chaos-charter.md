# E11-Q04 chaos charter: run record (baseline run)

- Ticket: E11-Q04 (#516), closed by this PR (ruling BQ-20 (ii)) · Run: 2026-10-31 · Base: `origin/main` at the branch point of this PR
- Artefacts: `packages/chart-engine/test/chaos/` (seeded unit suite, `unit` project),
  `packages/chart-engine/test/chaos/browser/context-loss-lane.mjs` (evidence-only browser lane),
  `docs/qa/charters/E11-charter-1-engine-chaos.md` (manual charter and session sheet; session 1 run, §4).
- **Baseline chaos run: 0 of 7 scenarios asserted in full, 6 in part (fake GL / fake clock, browser-lane
  evidence for G1/G2 on SwiftShader and on this host's GPU), 1 pending (G5); golden-image comparison
  pending #391 for every recovery row; charter session 1 run (§4), manual rows M1 to M7 not run.**
  This is a baseline; every pending row names its owning ticket (§7).

## §0 Honest scope

What the engine has at the base, and so what this run can assert:

| Area                               | At the base                                                                                                                      | Consequence here                                           |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Context loss                       | Built: `src/gl/context-loss.ts` (1 / 2 / 4 s attempts, `RESTORE_BUDGET_MS` 2000), automatic `degraded-2d` handoff (README BQ-53) | Asserted on the fake GL and the fake clock                 |
| `degraded-2d`                      | Built (E11-T05)                                                                                                                  | Asserted                                                   |
| Store-boundary rejection           | Built: `src/model/BarStore.ts`, `ModelRejection` → `ENGINE_DECODE_ERROR`                                                         | Asserted at the store                                      |
| Worker-boundary rejection          | Built: `rejectReason` / `layoutBytes` in `src/worker/protocol.ts`                                                                | Asserted at the runtime                                    |
| Runtime ↔ DataModel wiring         | Not built: a `data` batch only moves an element count in `src/worker/runtime.ts`                                                 | Hostile _values_ are asserted at the store, not end to end |
| Backpressure resync                | Built: one resync request per overload episode (`src/worker/host.ts`)                                                            | Engine-layer evidence only (BQ-04)                         |
| Panes in the runtime               | One (until E11-S09 #446); the context-restore bench scene has 3 panes and 100 000 bars                                           | G1's 3 panes asserted at the scene level only              |
| SDF atlas, IndexedDB               | Not built (E11-S11 #336)                                                                                                         | Pending                                                    |
| Visibility handling                | None in `src/`                                                                                                                   | G6 store and frame halves only                             |
| GPU out-of-memory, memory governor | None; `ENGINE_MEMORY_PRESSURE` absent (E11-S15 #448)                                                                             | Pending                                                    |
| A mounted chart                    | No route mounts the chart or SCR-048 (until SCR-030)                                                                             | The `role="alert"` end-to-end path is pending              |

C-13.6 (cited by id, list not copied): no scenario of this charter is a C-13.6 scenario; the nearest
by name are server-side and out of scope here (E45 and the platform epics). This record is not
C-13.6 release evidence.

## §1 Traceability

### Gherkin map

| G                        | Asserted now (test, in `test/chaos/`)                                                                                                                                                                                                                                      | Pending on                                                                                                           | Full requires                                   | Status  |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- | ------- |
| G1 restore within budget | `context-loss.test.ts` "loss during idle / pan / storm, 25 seeds" (codes once each; viewport, crosshair a11y summary, acks, frame stats, GL objects, uniforms equal a no-loss run; budget applied on the fake clock); "a seeded patch storm over 100 000 bars and 3 panes" | 3 runtime panes #446, crosshair series #388, golden pixels #391, atlas generation #336, mounted SCR-048 announcement | golden pixels; 3 runtime panes; a mounted chart | partial |
| G2 three losses in 10 s  | "three losses inside 10 s, 25 seeds" (each recovers; live GL objects and frame stats back to the start; functional after); "the 3-pane, 100 000-bar scene: three cycles"                                                                                                   | golden pixels #391                                                                                                   | golden-image comparison after each recovery     | partial |
| G3 permanent loss        | "ChartEvents.error: LOST once per attempt …"; "the engine hands off automatically …"                                                                                                                                                                                       | D-01 (#5230); F-01 SCR-118 link (#334)                                                                               | the SCR-118 link; a mounted chart; D-01 fixed   | partial |
| G4 malformed batch       | `feed-faults.test.ts` "10 malformed classes over 25 seeds"; "13 hostile classes over 25 seeds"                                                                                                                                                                             | runtime ↔ DataModel wiring (E12-T06 #399); `memoryBudgetMb` #448; pixels #391                                        | pixels instead of a fake-GL digest; the wiring  | partial |
| G5 sequence gap          | none for the Gherkin. Engine-layer evidence: "a seeded mixed-op storm: any dropped batch asks for exactly one resync per episode"                                                                                                                                          | socket-gap wiring (E12-T06 #399); F-05 stale indicator (E12-S10 #396)                                                | both                                            | pending |
| G6 background 10 min     | `pressure.test.ts` "10 min of rAF stopped with a live feed" (no frame backlog, one coalesced frame, store with no gap or duplicate)                                                                                                                                        | engine visibility handling, data-layer catch-up: E17-T05 #570                                                        | the catch-up and no-animation-replay halves     | partial |
| G7 100 cycles            | "inline / worker: 100 create / dispose cycles of two charts" (no GL object, listener, canvas or worker left; engine estimate equal first to last)                                                                                                                          | JS heap (browser lane: pending, see §4), GPU memory #519                                                             | measured heap and GPU memory within 5 %         | partial |

### Scope rows (26)

| #   | Scope case                                 | Test or status                                                                                                       | Maps to                   |
| --- | ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| 1   | Loss during idle                           | G1 "loss during idle"; browser lane `idle`                                                                           | G1                        |
| 2   | Loss during a pan                          | G1 "loss during pan"; browser lane `midPan`                                                                          | G1, US-CHART-006          |
| 3   | Loss during a data storm                   | G1 "loss during storm"; "a seeded patch storm over 100 000 bars and 3 panes"                                         | G1                        |
| 4   | Loss during atlas generation               | `pending: E11-S11 #336`                                                                                              | G1                        |
| 5   | Repeated loss, 3× in 10 s                  | G2 tests; browser lane `threeIn10s`                                                                                  | G2                        |
| 6   | Loss that fails to restore (SCR-048 path)  | G3 tests                                                                                                             | G3                        |
| 7   | Malformed binary frames                    | G4 "10 malformed classes" (overlap, misalignment, wrong type, unknown store / op)                                    | G4                        |
| 8   | Truncated frames                           | G4 "10 malformed classes" (truncated, overlong)                                                                      | G4                        |
| 9   | Out-of-order sequence numbers              | engine layer: G4 "13 hostile classes" (store order); socket half `pending: E12-T06 #399`                             | G4, G5                    |
| 10  | Sequence gap requiring resync              | engine layer: G5 storm (evidence only); socket half `pending: E12-T06 #399`                                          | G5                        |
| 11  | Duplicate frames                           | G4 "13 hostile classes" (duplicate time, out-of-order append)                                                        | G4                        |
| 12  | `NaN` and `Infinity` prices                | G4 "13 hostile classes" (non-finite time, volume, delta, tick size; non-finite params at the boundary)               | G4                        |
| 13  | Declared length above `maxBars`            | G4 "count above the ceiling" (boundary), "count above maxBars" (store)                                               | G4                        |
| 14  | 60 s feed stall then a burst               | `feed-faults.test.ts` "after the stall, a seeded append burst arrives whole"; UI-thread half `pending: E11-Q03 #445` | US-CHART-010              |
| 15  | Memory pressure to 70 % and beyond         | `pending: E11-S15 #448`                                                                                              | US-CHART-010              |
| 16  | GPU memory exhaustion                      | `pending: E11-S15 #448`                                                                                              | G7                        |
| 17  | Worker starvation, main thread blocked 5 s | `pressure.test.ts` "5 s of queued input and data go out bounded"                                                     | US-CHART-006              |
| 18  | 100 open / close cycles                    | G7 tests                                                                                                             | G7                        |
| 19  | DPR change mid-pan                         | `pending: E11-S10 #447`; manual M4                                                                                   | US-CHART-006              |
| 20  | Monitor disconnect                         | `manual: not executed` (M1)                                                                                          | G1                        |
| 21  | Window minimise / restore                  | `manual: not executed` (M2)                                                                                          | G6                        |
| 22  | Machine sleep / wake                       | `manual: not executed` (M3)                                                                                          | G1, G6                    |
| 23  | Tab backgrounded 10 min                    | G6 test (store and frame halves); manual M5                                                                          | G6                        |
| 24  | WebGL2 unavailable at startup              | `pressure.test.ts` "inline / worker: no WebGL2 at startup"                                                           | US-CHART-014 (disclosure) |
| 25  | WebGL2 lost for good, `degraded-2d`        | G3 tests                                                                                                             | G3                        |
| 26  | IndexedDB unavailable during atlas caching | `pending: E11-S11 #336`                                                                                              | US-CHART-008 (labels)     |

## §2 Results per case (2026-10-31)

All automated rows below passed: the package's vitest `unit` project over `test/chaos`
(`vitest run --project unit test/chaos`), 3 files, 20 tests passed, 25 `it.todo`. Every seeded case walks 25 seeds (20261031 to 20261055; the
100 000-bar scene and G6 walk the first 5) and puts the seed in every assertion, so a failure names it.

- Mutation check (local, reverted): removing the backend's buffer restore, its texture restore, the
  ack of a rejected batch, or the backpressure resync each turned a chaos test red. Removing the
  scene's `markAllData` on resume did not: the backend's `restore()` re-uploads every buffer itself,
  so that line is belt and braces at this base.
- Determinism: no wall clock (the repo guard `test/guards/no-wall-clock-in-unit.test.ts` passes over
  these files), no `Math.random`, no network, no sleeps.

## §3 Codes asserted

| Code                            | Where asserted                                                                          | Count and flag                                      |
| ------------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `ENGINE_CONTEXT_LOST`           | G1, G2, G3, F-14 fallback                                                               | once per attempt, `recoverable: true`, details 1..3 |
| `ENGINE_CONTEXT_RESTORED`       | G1, G2, F-14 fallback                                                                   | once per recovery, `recoverable: true`              |
| `ENGINE_CONTEXT_RESTORE_FAILED` | G3                                                                                      | once, `recoverable: false`                          |
| `ENGINE_NO_WEBGL2`              | startup without WebGL2 (both run modes); absent on the G3 handoff (README BQ-53, BQ-90) | once, `recoverable: true`, all five reductions      |
| `ENGINE_DECODE_ERROR`           | G4 boundary and store                                                                   | once per bad batch, `recoverable: true`             |
| `ENGINE_MEMORY_PRESSURE`        | `pending: E11-S15 #448` (absent from the code)                                          | —                                                   |
| `ENGINE_WORKER_LOST`            | cited, not re-run: `test/worker/host.test.ts` "Worker death is recovered" (H-06, H-17)  | —                                                   |

## §4 Browser lane output (evidence only)

Command: `pnpm --filter @candleviewer/chart-engine build`, then
`node packages/chart-engine/test/chaos/browser/context-loss-lane.mjs`. Chromium 156.0.8078.4
(headless), Playwright 1.64.1, Node 22.14.0, the bench's pinned software-GL flags (ANGLE on
SwiftShader) plus `--enable-blink-features=ForceEagerMeasureMemory`. Software GL is not GPU evidence
(E11-Q07 #519). `restoredMs` is the engine's own loss-to-first-frame time and includes the lane's
250 ms wait before `restoreContext()`.

| Case                   | Run mode | Codes                                                                         | restoredMs    |
| ---------------------- | -------- | ----------------------------------------------------------------------------- | ------------- |
| idle                   | inline   | LOST, RESTORED                                                                | 260           |
| mid-pan                | inline   | LOST, RESTORED                                                                | 269           |
| three losses in 10 s   | inline   | LOST, RESTORED ×3 (span 4.5 s)                                                | 259, 259, 258 |
| F-14, worker blocked   | inline   | LOST, RESTORED                                                                | 257           |
| F-14, transfer blocked | inline   | LOST, RESTORED                                                                | 260           |
| heap over 100 cycles   | —        | pending: the API threw `SecurityError` (not available in this headless build) | —             |

Some runs also post one informational `ENGINE_FRAME_BUDGET_EXCEEDED` on their first frames
(SwiftShader start-up; one of the five completed cases in the run above); it is not a chaos code and not counted. The heap half of G7 stays pending:
no approximation from `performance.memory`.

### Charter session 1 (2026-10-31, this host's GPU)

Ruling BQ-15. The same lane, same build, with the bench's software-GL flags swapped for ANGLE on
the OpenGL backend (`--use-gl=angle --use-angle=gl --ignore-gpu-blocklist --enable-gpu`) and Mesa's
D3D12 driver under WSL2. WebGL2's unmasked renderer read `ANGLE (Microsoft Corporation, D3D12
(NVIDIA RTX PRO 500 Blackwell Generation Laptop GPU), OpenGL ES 3.1)`: a real GPU through a
translation layer, not the reference machine's native Windows driver. Chromium 156.0.8078.4
headless, Playwright 1.64.1, Node 22.14.0. Without those switches this host's Chromium falls back to
SwiftShader or llvmpipe (software).

| Case                   | Run mode | Codes                              | restoredMs    |
| ---------------------- | -------- | ---------------------------------- | ------------- |
| idle                   | inline   | LOST, RESTORED                     | 254           |
| mid-pan                | inline   | LOST, RESTORED                     | 262           |
| three losses in 10 s   | inline   | LOST, RESTORED ×3 (span 4.4 s)     | 262, 259, 260 |
| F-14, worker blocked   | inline   | LOST, RESTORED                     | 263           |
| F-14, transfer blocked | inline   | LOST, RESTORED                     | 262           |
| heap over 100 cycles   | —        | pending: `SecurityError`, as above | —             |

Every case also posted one `ENGINE_FRAME_BUDGET_EXCEEDED` on its first frames (not a chaos code).
Oracles O1 to O3 held for the context-loss cases: each code once per episode, no silent
degradation seen. The physical disturbances M1 to M7 need a headed session on the reference
machine and stay open on the sheet; no pixel comparison (#391) was made.

## §5 Coverage contribution (`pnpm --filter @candleviewer/chart-engine test:cov`)

| Run                       | Statements | Branches | Functions | Lines |
| ------------------------- | ---------- | -------- | --------- | ----- |
| Before (without `chaos/`) | 97.66      | 89.82    | 96.80     | 98.51 |
| After                     | 97.67      | 89.85    | 96.90     | 98.53 |

Floor (C-9.4): ≥ 85 % for `packages/chart-engine`. The suite's value is the post-recovery
assertions, not new lines.

## §6 Defects and findings

| Id   | Severity / priority                                                     | Owning ticket          | Summary                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ---- | ----------------------------------------------------------------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D-01 | S2; **P0 candidate** (silent wrongness of the disclosed render profile) | #5230 (filed)          | After the restore-failed handoff the engine posts `ready` and `frame` with `renderProfile: "degraded-2d"`, but the facade's `frameStats` and `getStats()` keep saying `"full"`: the `frame` case in `packages/chart-engine/src/api/chart.ts` builds its stats by spreading the previous `FrameStats` and never reads `msg.renderProfile`, and `ready` updates only a variable that `stats()` no longer reads once a frame has arrived. The app maps `renderProfile === "degraded-2d"` to the reduced capabilities (README BQ-90), so the handoff's disclosure never reaches the user. Repro: `test/chaos/context-loss.test.ts`, G3, the two passing tests plus the `it.todo` naming D-01. Environment: unit project, fake DOM. Filed as #5230 under BQ-16; the `it.todo` names it. |
| F-01 | finding, known omission                                                 | E11-S02 #334 (SCR-048) | G3 asks for a link to renderer settings; SCR-118's route does not exist yet, so SCR-048 omits the action by design. Cleared when the SCR-118 route lands; a finding comment on #334 at merge (BQ-06).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |

The Gherkin's G3 wording ("choosing the fallback") differs from the ruled automatic handoff (README
BQ-53); the charter asserts the ruling.

## §7 Pending rows by ticket, and needs-owner

| Ticket                     | Rows                                                                                                   |
| -------------------------- | ------------------------------------------------------------------------------------------------------ |
| E11-T08 #391               | golden pixels for G1, G2, G4                                                                           |
| E11-S09 #446               | G1 at 3 runtime panes, pane ratios                                                                     |
| E11-S07 #388               | G1 with the crosshair series drawn                                                                     |
| E11-S11 #336               | loss during atlas generation; IndexedDB unavailable                                                    |
| E11-S15 #448               | memory pressure and `ENGINE_MEMORY_PRESSURE`; GPU exhaustion; `memoryBudgetMb` under adversarial input |
| E11-S10 #447               | DPR change mid-pan                                                                                     |
| E11-S13 #520               | focus, data cursor, DOM mirror announcements                                                           |
| E11-T07 #523               | F-14's `runMode` in the SCR-046 allowlist                                                              |
| E11-Q07 #519               | GPU memory within 5 %; heap if no isolated page                                                        |
| E11-Q03 #445               | the post-burst catch-up does not stall the UI thread                                                   |
| a route mounting the chart | G1 / G3 `role="alert"` end to end                                                                      |

Owners named by the ruling (BQ-04, BQ-05, BQ-06, BQ-16); each row becomes one comment on its
ticket at merge:

| Ticket       | Rows                                                                                     |
| ------------ | ---------------------------------------------------------------------------------------- |
| E12-T06 #399 | socket sequence gap → engine resync wiring (G5); runtime ↔ DataModel `data` batches (G4) |
| E12-S10 #396 | F-05 per-pane stale indicator after a gap (G5)                                           |
| E17-T05 #570 | engine visibility handling and the catch-up on foreground (G6)                           |
| #5230        | D-01: the facade's `frameStats.renderProfile` after the `degraded-2d` handoff (G3)       |
| E11-S02 #334 | F-01: the SCR-118 link; SCR-048's `role="alert"` once a route mounts the chart           |

## §8 Cross-references

E11-X03 #524 (shares the threat model's §9 cases; H-01 and H-02 run here as feed faults, H-03 is
X03's; findings are linked, not duplicated), E11-Q03 #445 (performance, cited not measured),
E11-Q07 #519 (GPU matrix), E12-Q06 #529 (asserts F-05 from the bar side), E47-Q06 #1371 (a11y of
degraded states), E11-Q06 #518 (regression pack: the test names above are its input). Threat-model
cases by id and class only: H-05, H-06, H-13 to H-17, H-20; CE-D03, D05, D10, D11, D13.

## §9 Rulings applied

The ruling of record on BQ-01 to BQ-22 (2026-10-31) took every BQ as proposed, with these
decisions; the rows above already reflect them.

- BQ-03: every `it.todo` names its owning ticket id; nothing is `.skip`.
- BQ-04 / BQ-05: owners named (§7): E12-T06 #399, E12-S10 #396, E17-T05 #570; no new issue.
- BQ-06: the ruled automatic handoff is asserted; F-01 is a finding comment on #334.
- BQ-08 (a): the suite runs per PR in `unit` under coverage; no nightly workflow here; the
  real-browser nightly lane is a row for the E11 epic. Deviation: the ticket's "nightly" and
  "standalone leak job" are not met as written.
- BQ-09: the browser lane resolves Playwright from `apps/desktop`; no new dependency; no workflow.
- BQ-11 / BQ-13: G7 asserted in parts (GPU memory pending #519); memory pressure pending #448.
- BQ-14: threat-model cases by id and class only (§8).
- BQ-15: charter session 1 run on this host's GPU (§4); the physical-disturbance rows stay open.
- BQ-16: D-01 filed as #5230; P2 and below route by comment at merge.
- BQ-17: no `src/` edits; `tsconfig.core.json` / `tsconfig.dom.json` gain `test/chaos`; the
  `engine-bench` diff is in the PR body (no regression).
- BQ-18: branch `chore/e11-q04-chaos-charter`, commit type `test(chart-engine)`.
- BQ-20 (ii): this PR closes #516; each pending row is one comment on its owning ticket at merge.
