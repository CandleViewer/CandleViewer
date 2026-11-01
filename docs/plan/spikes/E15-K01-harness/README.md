# E15-K01 harness (throwaway)

Spike harness for E15-K01 (#371): the pane-count budget curve and the measured capability profile. It is
**throwaway** (the E11-K01 and E14-K01 precedent): nothing imports it, it is not product code and it is not
promoted without a `feat/` ticket (C-4.5; BQ-03, BQ-07). It adds nothing to the engine package's `bench/` folder,
runs no baseline and gates nothing. The findings are in [`../E15-K01.md`](../E15-K01.md); the scenario id is
`layout-scaling` (the ticket's name; its `benchmarks/layout-scaling` path does not exist).

**It imports nothing from the engine package or from `apps/web`** (BQ-02 ruling, the E14-K01 rule). The helpers
in `lib.mjs` and `load.mjs` **mirror, they do not import**, the bench's definitions, so the numbers stay
comparable with the ones CI gates on:

| Here                                    | Mirrors                                                                                                                                                                                                      |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `lib.mjs` `percentile`                  | the bench's nearest-rank percentile: rank = ceil(p/100 × n) − 1, clamped                                                                                                                                     |
| `lib.mjs` `medianOfP95`, `isAdmissible` | the bench's median of per-rep p95s and its three-rep admissibility rule                                                                                                                                      |
| `lib.mjs` `mulberry32`, `generateBars`  | the bench's seeded PRNG and synthetic 100k-bar series (integer ticks, volatility clustering, rare gaps; seed 20260928)                                                                                       |
| `lib.mjs` `SWIFTSHADER_FLAGS`           | the bench's pinned CI Chromium flag set (software GL)                                                                                                                                                        |
| `load.mjs` `ProxyLoad`                  | the bench's B3/B4 GL load: 8 instanced draws of 2,500 quads and a 512-row heatmap column every 100 ms                                                                                                        |
| `lib.mjs` `classify`, `reducedTrigger`  | the app's `apps/web/src/lib/capability/frameProbe.ts`; the app's unit test `e15k01Fixture.test.ts` runs the app's own `classify` on the measured windows this harness writes and must reach the same answers |

## What it is, and what it stands in for

The engine has no candle, indicator or drawings layer yet (`layers/index.ts` is a placeholder, E18/E19/E14-T03),
so the panes are **stand-in scenes** on real WebGL2 (BQ-02 option b): the draws the engine will issue.

- **bare**: grid, wicks and bodies of the visible window (6 px per bar), panning one bar per frame: 3 draws.
- **indicators**: bare plus a stand-in for the R1 set (E13 v1): 7 overlay lines (SMA, two EMAs, VWAP,
  Bollinger) and 4 sub-panes (volume + MA, RSI, MACD + signal + histogram, Stochastic + ATR + OBV): 20 draws.
- **drawings**: indicators plus 200 two-anchor trend lines, every one transformed and submitted each frame: 21 draws.
- **orderflow-proxy**: `load.mjs`. An **estimate** for footprint/DOM panes (BQ-13).

Topologies (BQ-05): `worker-shared` (one render worker, one context, a viewport and scissor per pane),
`worker` (one render worker, one context per pane) and `inline` (main thread, one context per pane).

## Files

| File                                                         | Role                                                                                              |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| `run.mjs`                                                    | Node driver: serves this folder on `127.0.0.1`, runs every job, applies the rule, writes the JSON |
| `page.html`, `page.mjs`                                      | The page: pane layout over a 1600x900 plot area (dpr 1), the context probe, the sync bench        |
| `worker.mjs`                                                 | The render worker: the worker topologies and the worker half of the sync bench                    |
| `scene.mjs`                                                  | The pane scene, the R1 stand-in indicators, the drawings fixture and the measured loop            |
| `sync.mjs`                                                   | The SyncBus-shaped fan-out (BQ-12)                                                                |
| `lib.mjs`, `load.mjs`                                        | The mirrored helpers (above)                                                                      |
| `../E15-K01-results.json`                                    | Generated (then Prettier-formatted). Every number in the finding comes from it                    |
| `apps/web/test/lib/capability/fixtures/e15-k01-windows.json` | Generated (then Prettier-formatted): three legs' probe windows and the mirror's answers           |

## What is measured, and how

- **Frame time** = one frame of every pane submitted, every context flushed, then a 1x1 `readPixels` on
  the last context: it returns only when the GPU process has run the frame, so GPU time is inside the number
  (`gl.finish()` does not wait in Chromium). The submit (CPU) part is reported separately. p50 / p95 per
  rep over a 10 s window (about 600 frames at 60 Hz) after a 2 s warm-up, three reps per cell, every job in a
  fresh browser context, in a seeded shuffled order (`--seed 371`). The warm-up frames are kept for the settle
  measure (the trigger's and the probe's warm-up).
- **Devices**: `dgpu` and `igpu` are the host's GPUs through WSL2's Mesa d3d12 driver and ANGLE's GL backend;
  `swiftshader` is the bench's pinned CI flag set. The 4x CPU throttle is CDP `Emulation.setCPUThrottlingRate`
  (it does not reach a dedicated worker, so the throttled weak leg runs inline).
- **Long runs**: three 70 s runs to which the E15-D12 BQ-10 trigger is applied exactly as ruled.
- **Sync**: one `sync {groupId, timeRange, crosshair}` per rAF frame to N panes (binary search over 100k bar
  times per pane), fanned out on the main thread (then one batch posted to the worker) or posted once and
  fanned out in the worker; main-thread ms per frame, 360 frames after 60 dropped, three reps.
- **Contexts**: 20 WebGL2 contexts created on the main thread and 20 in a worker; which were lost.

## Run it

From `apps/web` (it resolves `@playwright/test` from there), one run at a time, nothing else heavy on the host:

```sh
node ../../docs/plan/spikes/E15-K01-harness/run.mjs --raw "$TMPDIR/E15-K01-raw.jsonl"
node ../../docs/plan/spikes/E15-K01-harness/run.mjs --raw "$TMPDIR/E15-K01-raw.jsonl" --resume   # after a crash, or to add a leg
```

Options: `--devices dgpu,igpu,swiftshader` (the default), `--reps 3`, `--warm-s 2`, `--window-s 10`,
`--long-s 70`, `--seed 371`, `--chromium <path>`, `--only <regex over leg/density/N>` (prints, writes nothing),
`--smoke` (tiny windows, writes to `$TMPDIR`). Each finished job prints one progress line and is appended to the
raw file; a job over 3 min is killed and recorded as failed. The full run is about 45 min. On a host without the
WSL GPU path run `--devices swiftshader`, or add a device entry with the reference machine's flag set (the owner
legs, `../E15-K01.md` §10).

The rule (budget, floor, headroom, cap, four-pane floor, AC1 tolerance, sync threshold, trigger checks) is the
`RULE` block at the top of `run.mjs`, written before the run; every value in it is PROPOSED.
