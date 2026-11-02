# E06-K02 prototype scene A — THROWAWAY CODE

Except `scene-graph.ts`, `scheduler-overhead.ts` and `pan-zero-upload.ts`: E11-S01 production bench code over `src/scene`, driven by Vitest (BQ-24).
Except `bar-store-mutations.ts`: E11-T03 production bench code over `src/model`, driven by Vitest.
Except `viewport-transform.ts`: E11-S03 production bench code over `src/viewport`, driven by Vitest (BQ-80).
Except `input-router.ts`: E11-S04 production bench code over `src/interaction`, driven by Vitest (BQ-112).
Except `scale-mode-switch.ts` and `autoscale-fit.ts`: E11-S05 production bench code over `src/viewport`, driven by Vitest (BQ-126).
Except `hit-pick.ts`: E11-S08 production bench code over `src/hit`, driven by Vitest (BQ-141).
Except `atlas-build.ts`: E11-S11 production bench code over `src/text`, driven by Vitest (BQ-275).
Except `candle-ring.ts` and `candle-series.ts`: E12-S06 production bench code over `src/layers`, `src/model` and `src/gl`, driven by Vitest.

This directory is **throwaway prototype code** for the M0 spike ticket E06-K02
("Prototype scene A: 100k-bar model, visible-window draw and LOD ladder"). It
is deliberately **not** production-quality:

- No React bindings, no public API stability, no option diffing.
- No real WebGL2 rendering — this environment has no docker/GPU/headless
  Chromium available, so GPU-stage costs (`paneRedraw` base, `compositePresent`)
  are **modelled** from measured, real per-frame counters (bars touched,
  columns produced, draw-call count, LOD level) using constants noted in
  `scene-a.mjs`'s header, not measured against a real GPU. Everything that
  _can_ be measured for real in Node (index math, LOD selection, decimation,
  momentum integration, allocation counts) _is_ measured for real.
- Per the ticket's "Do NOT": no footprint cells/SDF text (E06-K03), no
  heatmap (E06-K04), no multi-pane sync/crosshair polish/drawings/indicators
  (E11), no touch/pinch gestures.

It exists to (a) prove out the `BarStore`/`Viewport`/LOD-ladder math against
the harness contract from E06-K01, and (b) produce the B1/B2/B9 numbers this
ticket must report — see `docs/plan/spikes/E06-K02.md` for the findings this
spike feeds into E06-T01/E06-T02. It is not merged into `main`'s production
path; nothing under `src/` imports from here, and nothing here is exported
from the package's public entry points (`src/index.ts`).

## Files

- `bar-store.mjs` — columnar `BarStore` (time/OHLC/volume typed arrays, ring
  capacity doubling) per `docs/plan/26-chart-engine-design.md` §3.3.
- `viewport.mjs` — bar-index-space pan/zoom/momentum per §3.5.
- `lod.mjs` — LOD threshold selection with hysteresis + min/max decimation
  per §3.6.
- `scene-a.mjs` — `SceneA`, a `BenchScene` implementation (see
  `bench/scene.mjs`) wiring the above into the harness's `init/step/stats`
  contract, plus `extendedStats()` for the ticket's Observability counters
  (`visibleBars, barsTouched, currentLod, lodChanges, drawCalls,
bufferBytesUploaded, allocationsInFramePath`).

## Running it

```sh
node ./bench/scenes/run-scene-a.mjs --scenario=B1 --reps=3
node ./bench/scenes/run-scene-a.mjs --scenario=B2 --reps=3
node ./bench/scenes/run-scene-a.mjs --scenario=B9 --reps=3
```

Writes `bench/scenes/report-<scenario>.json` (same shape as the E06-K01
harness report) alongside a static-frame 10k-vs-100k scaling check and the
decimation spike-preservation assertion (see
`test/bench/scenes/*.test.ts` for the pytest^H^Hvitest-gated versions of
those same checks).

## Why no real GPU numbers

CONSTITUTION §9 required checks and this environment's toolchain do not
include docker, a headless Chromium binary, or Playwright's browser
downloads (none are installed here — see the PR's "Not run" section). The
E06-K01 harness is designed so a _real_ GPU-backed scene (drawing candles
through actual WebGL2 in real headless Chromium, per `PINNED_CHROMIUM_FLAGS`
in `bench/report.mjs`) can replace the modelled cost constants in
`scene-a.mjs` without touching the harness, the driver, or the report
pipeline — that swap is explicitly **E06-T01**'s job (the runtime matrix),
not this ticket's.
