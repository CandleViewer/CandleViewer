# @candleviewer/chart-engine

Custom WebGL2 chart engine (candles, footprint, volume/market profile, CVD, DOM
heatmap). See `docs/plan/26-chart-engine-design.md` and ADR-0002.

## The package contract (C-2.16)

- **Framework-free.** No React, no application store, no app import (`apps/*`). The React
  ergonomics live in `apps/web/src/chart/` (`<Chart>`, `<Pane>`, `useChartApi()`,
  `useCrosshair()`), which own React lifecycle and option diffing only.
- **No I/O.** No `fetch`, `XMLHttpRequest` or `WebSocket`, no exchange (Bybit) knowledge. The
  host decodes the wire and hands the engine typed data.
- **Transferable typed arrays in, pixels and events out.** Prices are `Int32Array` integer ticks
  from a per-series `priceOrigin` with its `tickSize`, never float prices (§3.3: float32 loses
  precision at BTC magnitudes); times are `Float64Array` microseconds since the epoch. Output is
  the canvas plus the typed events of `ChartEvents` (`crosshair`, `frameStats`, `error`, ...).
- **Theme as a token object.** The engine never imports the design system: the host resolves
  tokens into `ThemeTokens` (`colors["color.chart.background"]` and friends) and passes them to
  `createChart` / `setTheme`.
- **No DOM globals.** `src/core`, `src/layers`, `src/scene` touch no DOM; the one DOM adapter is
  `src/host/`, which reaches the document through `container.ownerDocument`.

Enforcement, each failure naming C-2.16: `eslint.config.mjs` (`no-restricted-imports` for
react / react-dom / `apps/*` / a `/bybit/i` path, `no-restricted-globals` for fetch / XHR /
WebSocket / DOM globals, `no-restricted-syntax` for a `/bybit/i` symbol name and
`globalThis.fetch`-style access) and `.dependency-cruiser.js` (`chart-engine-no-react`,
`chart-engine-no-exchange`, `packages-not-to-apps`). `tsc` enforces the DOM split too:
`tsconfig.json` is solution-style and references `tsconfig.core.json` (no DOM lib: core, layers,
scene, gl, text, worker, plugins, bench, test) and `tsconfig.dom.json` (`src/index.ts`, `src/api`,
`src/host`, `test/api`); `pnpm typecheck` runs both, and ESLint's project service resolves each
file, including unsaved editor text, to the program that owns it.
`test/guards/c216-boundary.test.ts` proves every one against the real configs without committing a
violating file.

## Public API (`src/index.ts`)

The package root exports `createChart` (its one runtime export) and every type the §8 sketch
names, and nothing the sketch does not name (BQ-6); `test/api/surface.test.ts` holds the frozen
name list and both directions of that rule, so a widening shows up in review. The
facade lives in `src/api/` (`chart.ts`, `pane.ts`, `scales.ts`, `types.ts`). Today
`createChart` is a stub: it mounts a canvas sized to the container (CSS px times the device
pixel ratio, measured once at mount), paints `color.chart.background`, mounts the visually
hidden DOM mirror root (05 §6.1), returns synchronously, and emits the first `frameStats` (with
`renderProfile` from a lazy WebGL2 probe) on the next task. Series, overlay and indicator handles
record their lifecycle only; the stores, scene graph, GL backend and worker are E11-T03,
E11-S01, E11-S02 and E11-T02.

```ts
import { createChart, type CandleData } from "@candleviewer/chart-engine";

const chart = createChart({ container, theme }); // theme: ThemeTokens from the host
const off = chart.subscribe("frameStats", (s) => console.debug(s.renderProfile));
const pane = chart.addPane({ heightRatio: 1 });
const candles = pane.addSeries("candles", {
  upColorToken: "color.candle.up",
  downColorToken: "color.candle.down",
});
const bars: CandleData = {
  time: new Float64Array([1_700_000_000_000_000]), // µs epoch
  open: new Int32Array([0]),
  high: new Int32Array([12]),
  low: new Int32Array([-3]),
  close: new Int32Array([8]),
  volume: new Float32Array([1.5]),
  priceOrigin: 65_000,
  tickSize: 0.1,
};
candles.setData(bars); // buffers are transferable
off();
chart.dispose(); // idempotent
```

The stub's initial engine chunk (`dist/index.js`) is 7,799 bytes, 2,598 bytes gzipped: the
baseline later tickets are measured against for budget #9 (`06-performance-and-load-standard.md`
§2).

## Design deltas (E11-T01)

Where §8 of `26-chart-engine-design.md` and the shipped package disagreed. The public surface
follows §8 in every case; an existing caller keeps working through a non-root path.

| BQ   | Where                                   | §8 / the ticket                                                                                                                                                                                                          | Shipped                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ---- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BQ-1 | `CandleData` vs `packages/protocol`     | The ticket: a protocol `BarsBatch` payload is assignable to `CandleData` without a hand-written mapper.                                                                                                                  | **Not assignable as generated.** `generated.ws.BarsSymbolBarTypeParam` (and `StructuredBars`, `DecodedBars`) is row-oriented (`bars: {...}[]`), carries prices and volume as decimal strings (`o`, `h`, `l`, `c`, `v`), times as epoch ms (`t_ms`; `bigint` `tsMs` in the binary decoder), and no `priceOrigin` / `tickSize`. `CandleData` is columnar `Int32Array` ticks and `Float64Array` µs. A columnar decode step (E11-T03 / E12) is needed; `apps/web/test/chart/protocol-candle-contract.test.ts` pins each reason and flips when the protocol changes. Orchestrator ruling (2026-10-29 21:22Z): see C-1.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| BQ-2 | Package root exports                    | The root exports §8 only.                                                                                                                                                                                                | The pre-§8 scaffold exports (`createEngine`, `EngineHandle`, `EngineTheme`, `EngineOptions`, `EngineStats`, `RenderFlags`, `FrameState`, `DEFAULT_RENDER_FLAGS`, `animationWorkUnits`, `stepFrame`, `CHART_ENGINE_VERSION`) left the root. apps/web's appearance and a11y-preference hosts still use them, so they are served at `@candleviewer/chart-engine/compat` until those hosts drive a `Chart`. `ThemeTokens` has `EngineTheme`'s exact shape, so one token object feeds both. `./compat` is removed under E11-T09 (#1404, the public-API freeze): before the freeze those apps/web hosts drive a `Chart` through §8 and the entry is deleted.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| BQ-3 | `Chart` members, `createChart`          | §8's `Chart` has no accessibility query and the sketch never declares `createChart`; the ticket requires `getDomMirrorRoot()` and the 05 §6.1 visible-window / focused-unit query from day one, and lists `createChart`. | `Chart` adds `getDomMirrorRoot()`, `getVisibleWindow()` and `getFocusedUnit()` (both null until the data plane lands), with `VisibleWindow` and `FocusedUnit`; `createChart(opts: ChartOptions): Chart` is declared. §8 now shows all four (C-15.4).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| BQ-4 | Types §8 names but does not define      | `ThemeTokens`, `Density`, `PaneId`, `PaneOptions`, `TimeScale`, `PriceScale`, `Unsubscribe`, the handles, option bags and plugin context types.                                                                          | Each in its narrowest form (`src/api/types.ts`): `PaneId`, `TextureId`, `LutId` are branded; `TimeScale` / `PriceScale` carry only a visible-range getter and one setter; `PaneOptions` is `{ heightRatio? }`; the candle, line, histogram, profile and bubble option bags hold only colour tokens and one parameter each, for E12 / E13 to extend; `SeriesDataMap.heatmap` is `readonly HeatmapColumnData[]`, its delta one column. New data contracts E12 / E13 compile against: `LineData` (`time` µs `Float64Array`, `value` `Float64Array`), used by `line`, `area`, `baseline` and `histogram`; `ProfileData` (`priceLevel` `Int32Array` ticks, `volume` / `delta` `Float32Array`, `priceOrigin`, `tickSize`); `BubbleData` (`time`, `price` ticks, `size`, `side: Uint8Array` with 0 = sell and 1 = buy, `priceOrigin`, `tickSize`); and `SeriesDeltaMap` keeps an entry for every type (§8 types `append` for all of them), with a per-type merge rule from 26 §3.3: `candles`, `bars` and the four `LineData` types patch the last bar held with the payload's first bar when the times match and append the rest; `footprint` upserts cells by bar index (`upsertFootprintCells`); `profile` replaces the profile held (`replaceProfile`); `heatmap` pushes one column; `bubbles` only append. E11-T03 and E12 confirm these rules before E12 builds on them. Widening any of them is that owner's decision. |
| BQ-5 | Build and type tests                    | The ticket names `tsd` for the type tests.                                                                                                                                                                               | `tsd` is not in the lockfile and no dependency was added: the type tests are Vitest `expectTypeOf` assertions checked by `tsc --noEmit` (`pnpm typecheck` includes `test/`), plus a checker-driven snapshot of the root's exports. `tsup` (already present) builds the new `compat` entry.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| BQ-6 | Which supporting types the root exports | The ticket lists 19 names plus the five data shapes; the README said "exactly the §8 surface".                                                                                                                           | The rule is: the root exports every type the §8 sketch names, and nothing it does not (54 type names today, e.g. `Viewport`, `Rect`, `Point`, `Range`, `Params`, `LutId`, `Drawing`, `Modifiers`). `LineData`, `ProfileData`, `BubbleData`, `TimeRange` and `PriceRange` are deliberately not exported: §8 does not name them, so they are reachable only through `SeriesDataMap` / `SeriesDeltaMap` and the scale types. `Range` shadows the DOM lib's global `Range` in a module that imports it; import it under an alias there.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| BQ-7 | Price storage: spike and §3.3           | §8 and the §3.3 precision note: OHLC as `Int32Array` ticks from `priceOrigin`.                                                                                                                                           | Two sources still say float. The spike's `bench/scenes/bar-store.mjs` stores OHLC as `Float32Array` from rows of `{tOpenMs, o, h, l, c, v}` (ms, float prices), and `26` §3.3's `BarStore` block reads `open/high/low/close: Float32Array (scaled)`. Not changed here (the spike feeds the bench baseline; the store is E11-T03's): E11-T03 must build `BarStore` on `Int32Array` ticks and µs `Float64Array` time, and correct the §3.3 block in its PR.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| BQ-8 | The React binding vs the §8 sketch      | `<Chart options onCrosshair syncGroup>`.                                                                                                                                                                                 | `syncGroup` is a field of `options` (a recreate key, as `ChartOptions` has it); there is no `onCrosshair` prop, the `useCrosshair()` hook replaces it (latest value only, no per-event React state); a required `label` prop names the chart region (05 §6.1); an optional `onFrameStats` prop. §8's binding sketch now shows this shape (C-15.4).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| BQ-9 | The background token                    | The ticket: the stub paints `color.chart.background`.                                                                                                                                                                    | No design-system token has that name: `16` §2 names `color.surface.canvas` the chart background, and apps/web's host (`features/appearance/chartColorMode.ts` `ENGINE_TOKENS`) does not supply the key, so in the app today the stub's canvas is cleared, not filled; the acceptance criterion holds with the test fixtures only. The engine keeps the ticket's key; the token name is for the design system and E11-T04 (#390) to settle, and the host maps it when the GL backend (E11-S02) first draws.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| C-1  | AC reading for BQ-1                     | The ticket: "protocol types are assignable without adapters".                                                                                                                                                            | Orchestrator ruling (2026-10-29 21:22Z): the criterion is met by the pinned negative test that names each reason the generated bars payload is not assignable (`apps/web/test/chart/protocol-candle-contract.test.ts`) plus the columnar decode step owned by E11-T03 (#339); no hand-written mapper ships in this package.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

## Render worker and inline mode (E11-T02)

`src/worker/` carries the §6 protocol (`protocol.ts`), the one render runtime both run modes use
(`runtime.ts`), the dedicated module worker entry (`render-worker.ts`, built as
`dist/render-worker.js` and loaded as `new URL("./render-worker.js", import.meta.url)`, never a
`blob:` URL) and the main-thread host (`host.ts`). `createChart` picks `RunMode.worker` when the
realm has `OffscreenCanvas` and the canvas can transfer its control, else `inline`
(`ChartOptions.runMode` overrides it). Every chart on a page shares one runtime and one frame
callback. `data` buffers are always transferred (the sender's `ArrayBuffer` is detached in both
modes); at most two batches per store are in flight, the rest conflated. A lost worker is
restarted after 1, 2 and 4 s, then `error { code: "ENGINE_WORKER_LOST", recoverable: false }`
carries the SCR-048 correlation id. Counters: `engine.worker.messages_dropped`, `.conflated`,
`.restarts` (`ChartHost.counters`).

## Design deltas (E11-T02)

Where §6 of `26-chart-engine-design.md` and the ticket were silent or disagreed; the narrower shape
shipped in each case.

| BQ    | Where                        | Shipped                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ----- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BQ-10 | Messages §6 does not list    | Backpressure needs an acknowledgement and `export` needs a reply: worker to main `ack { id, store }` (one per `data`, rejected ones included) and `exported { id, reqId, blob }`; main to worker `command { k: "release" }` deregisters a chart from the shared worker. `frame` also carries `runMode` (ticket observability). §6 now lists them (C-15.4).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| BQ-11 | `runMode: "worker"` override | Where `OffscreenCanvas` or `transferControlToOffscreen` is missing the chart runs inline even when `worker` is asked for: there is nothing else it can do. `ChartInternal.runMode` reports the mode chosen. §8's `FrameStats` is frozen, so `runMode` is not added to it; it travels in `ready` and `frame`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| BQ-12 | Envelope details             | `ChartId` is a number; `ThemeLut` is the resolved colour-token map; `ChartConfig` is `{ bench, syncGroup }`; `BufferLayout` is `{ count, columns: { offset, bytes }[], params }`, and the columns must tile the buffer exactly (in range, aligned, non-overlapping; a non-empty batch has at least one column). Input rows are `[type, x, y, buttons, modifiers, dt]`; a wheel row carries `deltaY` in the `buttons` slot. `input` goes out at most once per frame per kind. `resize` sets the backing store in the runtime and the canvas's CSS box on the main thread, in the same frame, in both modes. The ≤ 20/s per store `data` rate is not enforced on the host: the two-in-flight rule (BQ-16) bounds it.                                                                                                                                                                                                                                                   |
| BQ-13 | Which series send `data`     | Only `candles` and `bars` (the `bars` store): the other stores and their encoders are E11-T03 / E12's. The envelope has no series id, so a chart has one store of each kind. A batch whose six columns tile one `ArrayBuffer` (the decoder's layout) is sent zero-copy; separate arrays are packed into one buffer first (one copy), and that buffer is transferred.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| BQ-14 | The runtime's stub renderer  | No `DataModel` (E11-T03), GL (E11-S02), hit index or viewport math (E11-S03) yet: the runtime pans, zooms and tracks the crosshair over a time window only (`priceLow`, `priceHigh`, `barSpacing` report 0), every pick is a miss, the LOD is whatever `setLod` set, and the background is painted on the frame, no longer inside `createChart` (the T01 tests advance one frame).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| BQ-15 | Crash recovery               | The host keeps no copy of transferred data, so the "snapshot request" is `visibleRangeNeedsData` for the last viewport once the restarted worker is `ready`; the host replays the theme, the last size (`init` carries its dpr, then a `resize`), the viewport, the LOD, series options and drawings; transient commands (`pickAt`, `export`) are not replayed. A transferred canvas cannot be transferred again, so a fresh canvas, sized to the container as it is then, replaces it in the DOM. The correlation id is in the `error` message (§8's event has no field). The restart budget resets only when a worker dies 10 s or more after its `ready` (`HEALTHY_RESET_MS`), so one that crashes right after `ready` still runs out. Once the budget is spent, a pending `takeScreenshot` rejects instead of hanging. A worker that cannot be created at all, or a canvas that will not transfer, runs the chart inline instead of throwing from `createChart`. |
| BQ-16 | Backpressure bound           | Held-back batches per store are capped at 4: a batch merges into the queue's tail only when op and layout shape match (`append` / `prepend` concatenate, `patch` last-wins, `replace` clears the queue); past the cap the oldest is dropped and counted, and the chart emits `visibleRangeNeedsData` for the last viewport (once per overload episode, re-armed when the queue drains) so the data layer re-sends the store. Batches a restart discards are counted in `messages_dropped` too.                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| BQ-17 | Browser-only criteria        | The repo has no real-browser harness for the engine yet, so "a 2 s main-thread block keeps panning" and the heap-snapshot check are covered by the `bench/matrix` worker run (B7, `storm-worker.mjs`) and the unit transfer proof; the Playwright / Electron run is E11-Q01 / E11-T06. The a11y throttle (≤ 2 announcements/s) is the live-region layer's (E11-S13); the `Performance.mark()` transport slice for SCR-046 is E11-T07. Per-frame allocation is not yet zero: each `input` batch is a fresh `Float32Array` (the transfer detaches it; a pool fed by returned buffers needs a reply message), `captureInput` builds a row per event, the crosshair summary is a new string and `frame` a new object; the zero-allocation frame test of 26 §3.2 rule 4 is E11-S02's with the GL path.                                                                                                                                                                    |
| BQ-18 | Bench mode and the LOD trace | The switch is `ChartHostOptions.bench` (`src/worker/host.ts`, internal): it makes the runtime post `frame` every frame, which is the C-Q02-1 LOD trace hook, and the parity test drives it. §8's `ChartOptions` has no internal or test option, so `createChart` always passes `false`; exposing it to the bench harness is E11-T06's.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| BQ-19 | §6 payloads                  | `ready` carries `{ runMode, renderProfile }`: the selected `RenderProfile` is the whole capability report until E11-T05 owns detection. `frame` adds `renderProfile` and `runMode` (the ticket's observability). `pick` has no `cell`: there is no footprint hit index before E11-S08 / E12, so the field is left out rather than always empty. Every message carries the chart `id` (`null` on a worker-wide `error`), because one worker serves every chart on the page.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |

## Scene graph (E11-S01)

`src/scene/` (internal) is `26` §3.1's fixed tree walked as a flat array rebuilt only on `LAYOUT`;
nodes carry `dirty` flags, `critical` and an `06` §4.4 `deferClass`, and never issue GL calls. A
collect's output is a patch set over retained batches, not the draw list; the PR3 `BatchBuilder`
owns the retained list and resolves visibility. The scheduler and `LayoutEngine` follow in PR2/PR3.

## Design deltas (E11-S01; from BQ-20, as BQ-10 to BQ-19 are E11-T02's)

| BQ    | Where                   | `26` / the ticket                                              | Shipped                                                                                                                                                                                                                                                               |
| ----- | ----------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BQ-20 | `zIndex` ties           | Silent.                                                        | Stable by insertion: a node lands after every sibling with an equal or lower `zIndex`.                                                                                                                                                                                |
| BQ-21 | Property test           | fast-check, 10 000 cases.                                      | fast-check is not in the lockfile and no dependency is added: a seeded `mulberry32` loop (`bench/fixtures/rng.mjs`) runs the same 10 000 cases.                                                                                                                       |
| BQ-22 | Which nodes a mark hits | Viewport: "all series"; data: "the affected series".           | Viewport and theme mark every drawable node (content in any layer and both axes), not the containers; data marks one content node by id (the store-to-series mapping is E11-T03's); a one-pane resize marks that pane and the time axis, so PR3 resizes siblings too. |
| BQ-23 | A "successful collect"  | Flags clear after a successful collect; no failure path.       | `collect(sink)` returns `true` on success; `false` keeps the flags for the next frame. A hidden node is not collected and keeps its flags too.                                                                                                                        |
| BQ-24 | The `scene-graph` bench | A `bench/` scenario.                                           | A TypeScript module driven by Vitest (the counted half in `unit`, the timed half in `perf`, which engine-bench runs): Node 20 runs no `.ts`, so there is no `run-scene-*.mjs` CLI for it.                                                                             |
| BQ-25 | Internal shapes         | §8 `PickResult`, `Viewport`; a mutable `zIndex`.               | `PickSlot` and `FrameContext.viewport` are internal placeholders, not the §8 types (E11-T02 / E11-S03 own those). `zIndex` is `readonly`, read at attach; PR3 adds `setZIndex` with a re-sort. `NullSeries` sits in `src/scene/` for the bench and is never exported. |
| BQ-26 | Shedding and animation  | `06` §4.4: lower cadence, focus-only rung 4; `26` §3.2 rule 2. | `frame(…, shedUpTo)` skips a rung for that frame only; the PR2 scheduler owns the cadence (heatmap 250 ms, indicators every second frame), rung 4's focused-pane predicate (critical nodes stay live) and a re-mark path for an animating node.                       |

## Scripts

- `pnpm --filter @candleviewer/chart-engine build` — tsup ESM build with `.d.ts` (entries:
  `index`, `compat`, `bench`).
- `pnpm --filter @candleviewer/chart-engine test` / `test:cov` — Vitest.
- `pnpm --filter @candleviewer/chart-engine bench` — writes `bench/results.json`
  (`frameTimeMs.{p50,p95,p99}`, `drawCalls`, `memoryMb`); `bench:baseline` writes
  `bench/baseline.json` for the `main`-branch comparison (CONSTITUTION §9 #16).

## Benchmark harness (E06-K01)

`bench/` is a deterministic, seeded benchmark harness for the M0 report (see
`docs/plan/06-performance-and-load-standard.md` §7, `docs/plan/26-chart-engine-design.md`
§13). It is **not** production engine code — it drives whatever scene a
`BenchScene` implementation (`bench/scene.mjs`) provides via a tiny interface,
so the K02/K03/K04 prototype scenes plug in unmodified.

```sh
pnpm bench --scenario=B5 --runtime=chromium --reps=3 --seed=20260928
```

- `--scenario` — one of `B1 B2 B3 B4 B5 B7 B9 B10` (`bench/driver.mjs`
  `SCENARIOS`); each maps to a time-parameterised scripted input sequence
  (pan, zoom sweep, footprint hold, heatmap stream, combined, live-update
  storm, cold-init, 30-min soak) so a slow machine executes the same logical
  motion as a fast one.
- `--runtime` — `chromium` (default/only wired target today), or `electron`/
  `tauri` (stubbed per this ticket's scope — real driving is E06-T01).
- `--reps` — repetitions; **default 3**. Fewer than 3 marks the report
  `"not admissible for ADR evidence"` (`bench/stats.mjs`).
- `--seed` — any string/number, hashed to a 32-bit seed for the mulberry32
  PRNG in `bench/fixtures/rng.mjs`; the fixture generator is byte-reproducible
  for a given seed (asserted by `test/bench/fixtures-determinism.test.ts`).

Every run writes `bench/report-<scenario>.json` (schema: `scenario, runtime,
runtimeVersion, machine{cpu,gpu,driver,os,webview2Version?}, seed, lodProfile,
repetitions, admissibleForAdrEvidence, p50, p95, p99, perStageMs{},
unattributedMs, drawCalls, uploadedBytesPerSec, textureMemMB,
peakProcessMemMB, peakProcessMemSource, gpuFlags[]}`) and
`bench/report-<scenario>.md` (human summary); both are generated artefacts
and are **not** committed (see `.gitignore`). `perStageMs` covers the nine
frame stages named in `06-performance-and-load-standard.md` §4.3 (input
handling, data-window recompute, candle geometry, footprint text/geometry,
heatmap upload, pane redraw, overlay redraw, DOM-mirror sync,
composite+present); the residual left over from the measured frame time is
reported as `unattributedMs` and the report writer fails the run if it
exceeds 10%.

The pinned headless-Chromium GPU flag set (`bench/report.mjs`
`PINNED_CHROMIUM_FLAGS`, printed in every report so results stay comparable
across weeks) is:

```
--use-gl=angle --use-angle=swiftshader --disable-gpu-vsync --enable-webgl2 --force-color-profile=srgb
```

The machine descriptor (CPU, GPU, driver, OS, and — on Tauri — the WebView2
runtime version) is captured automatically by `bench/machine.mjs`; a run
missing any required field fails rather than reporting anonymous numbers.

## Matrix benchmark in CI and the baseline-update policy (E06-T02)

`.github/workflows/perf-engine-matrix.yml` runs the E06-T01 matrix (`bench/matrix/`) on every PR that
touches this package (headless Chromium, B1 B2 B3 B4 B5 B9) and nightly (Electron, the full set with
B7 and the 30-minute B10 soak). B7 is nightly-only because it stalls on the hosted runner's software GL
(the M0 report's U5): its first PR run hung until the harness timeout.

It is **recording only** in R0: `bench/matrix/ci-compare.mjs` publishes the comparison with the
committed baseline in the job summary and the run's report as an artefact, and a regression never
fails the build. A run that produces no valid report does fail the job. Making it a required gate is
E11-T06. These hosted software-GL numbers are not reference-hardware evidence (the committed matrix
on `main` is); they are regression tracking only. The M0 findings report it keeps alive is
`docs/plan/spikes/E06-M0-report.md`.

Baselines live in `bench/matrix/baselines/<runtime>-ubuntu-latest.json`, one per runtime and runner
class. The policy (`docs/plan/06-performance-and-load-standard.md` §7.4): baselines **move forward only**
(get stricter or stay flat). The one exception, a deviation from §7.4 that this recording-only job needs,
is a toolchain or runner-image change (Chromium, Electron, driver or hosted image), which can shift every
figure without any code change; such a move still follows rules 1–3.

1. A baseline moves **only through a reviewed PR** whose description states why it moves (the change
   that caused it, or the toolchain bump) and quotes the old and new figures.
2. The file is the **unmodified report JSON from a CI artefact of a `main` run** of the same workflow and
   runner class (`ubuntu-latest`, no GPU). Never a laptop, a reference-machine or a PR-branch run: those
   numbers are not comparable with the runner's.
3. A baseline is never re-taken to make a regression disappear; a regression is fixed, or accepted in
   the PR with the rationale on record.
4. Until a runtime's file exists the job records "no baseline yet" and still publishes its report; the
   first file is committed from the first green `main` run (for Chromium, a `workflow_dispatch` on `main`;
   that job runs on PRs and on dispatch, never on a push).
