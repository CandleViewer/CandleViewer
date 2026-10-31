---
description: Rules for packages/chart-engine (custom WebGL engine) - no DOM/React in core, worker + OffscreenCanvas, benchmark gate max 5% regression.
---
# Chart engine (`packages/chart-engine/`)

Source: `docs/plan/26-chart-engine-design.md`, ADR-0002, CONSTITUTION C-2.16, §9 #4 and #16, C-14.2.

## Independence (C-2.16)
- **No React, no network, no Bybit/exchange knowledge, no app imports.** Input is typed data via the
  engine's public API; output is pixels plus typed events (hover, click, viewport change).
- **No DOM in `src/core/` or `src/layers/`**: no `document`, `window`, `HTMLElement`. DOM glue (canvas
  mounting, pointer events, resize observer) lives only in a thin host adapter.
  Enforced by dependency-cruiser + ESLint `no-restricted-globals`.

## Threading
- Rendering runs in a Web Worker with `OffscreenCanvas` (`src/worker/`). The main thread only forwards
  input events and receives lightweight notifications.
- Data crosses threads as transferable `ArrayBuffer`s / typed arrays (struct-of-arrays), never large JSON.
- The fallback path (no OffscreenCanvas) must reuse the same core code.

## Rendering
- WebGL2; instanced draws; upload only changed buffer ranges (no full re-upload per frame).
- No per-frame allocations in the render loop (reuse typed arrays and pools; no per-frame closures).
- Dirty-flag rendering: draw only when data, viewport or theme changed.
- Theme arrives as a token object; the engine does not import the design-system package.
- Budgets (C-14.2): 60 fps, <16 ms p95 frame time on the reference dataset.

## Benchmarks (`engine-bench`, §9 #16)
- Any PR touching `packages/chart-engine/**` runs `pnpm --filter @candleviewer/chart-engine bench`.
- **Fail on >5% regression** in frame time, draw calls or memory vs the `main` baseline (median of 5,
  headless Chromium, fixed dataset). Paste the bench diff in the PR.
- `bench:baseline` updates need CODEOWNER approval and a written justification.
- Wall-clock bounds in `*.perf.test.ts` go through `budget(<spec>)` (one CPU-probe runner calibration, capped at 3x; owner: `docs/plan/06-performance-and-load-standard.md` §7.4). That is normalisation, not loosening: never change a spec number, and `REFERENCE_CPU_MS` in `packages/config/src/perf-calibration.mjs` is a baseline-class change.
- Every new layer adds a benchmark scenario under `bench/` in the same PR.

## Tests
- Vitest, coverage >=85% (`unit-engine`). Pure math (scales, viewport, hit-testing, LOD/decimation) gets
  property tests. Visual regressions via screenshot tests in headless Chromium with a fixed seed.
- Wall-clock budget asserts live in `*.perf.test.ts` (vitest `perf` project, run by `engine-bench` without coverage; `unit` runs under coverage). Never loosen a budget or skip without this split.
