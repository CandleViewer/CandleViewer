# E11-K01 harness (throwaway)

Spike harness for E11-K01 (#332): it measures the SDF glyph atlas for O2 with real font rasterisation, the font being a parameter. It is **throwaway**
(BQ-182, the E37-K01 precedent): nothing here is product code, nothing imports it, and E11-S11 implements the
pipeline in `packages/chart-engine/src/text/`. The findings are in [`../E11-K01.md`](../E11-K01.md).

## What it runs

Headless Chromium through Playwright, which `apps/web` already installs. There is no new dependency.

| File               | Role                                                                                                                                                                                                                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `run.mjs`          | The Node driver. It checks coverage from the font files, serves the page on `127.0.0.1`, runs the matrix and writes `../E11-K01-results.json` and `../E11-K01/img/*.png`                                                                                                                   |
| `cmap.mjs`         | Reads the font's `cmap` (formats 4 and 12), so a glyph counts as covered only when the font has it. A Chromium fallback face never counts (Sc2, BQ-180)                                                                                                                                    |
| `glyphs.mjs`       | The glyph sets (BQ-172): `FULL` (194) and `FLOOR` (141), the cell set, the confusable pairs and the sample line                                                                                                                                                                            |
| `atlas-worker.mjs` | The §3.7 pipeline in a module worker. A `FontFace` is loaded from the font bytes, each glyph is drawn with OffscreenCanvas `fillText`, cropped to its ink box, run through the two-pass EDT (`packages/chart-engine/bench/scenes/edt.mjs`, unchanged) and shelf-packed into one R8 texture |
| `page.mjs`         | Cold generation (a fresh worker per sample) and warm load (the real IndexedDB, for two record shapes)                                                                                                                                                                                      |
| `legibility.mjs`   | WebGL2 (SwiftShader) draws the atlas with the §3.7 `fwidth` band and with the shipped fixed band, beside native `fillText`. It reports per-glyph SSIM, confusable-pair separation and the ink heights used for the LOD floor                                                               |

## Run it

Run from `apps/web`, one process at a time, and not while the bench runner's `perf-pack-full` job is active.
The fonts are taken **by path**, so the font is a parameter. The family choice is final (`16` §2.2); the
files are not vendored yet (G-42). Once `packages/ui/src/fonts/` exists, the rerun is one command on the
exact WOFF2 bytes the cache key hashes:

```sh
node ../../docs/plan/spikes/E11-K01-harness/run.mjs --mono '../../packages/ui/src/fonts/JetBrainsMono[wght].woff2' --ui ../../packages/ui/src/fonts/InterVariable.woff2
```

Until then, the VR image's TTF builds (`fonts-jetbrains-mono`, `fonts-inter`; `packages/ui/README.md`)
give a valid rerun only when the `fonts[].version` they record in the results equals the shipped files'
version; their `sha256` differs from the WOFF2's by construction:

```sh
node ../../docs/plan/spikes/E11-K01-harness/run.mjs --mono "$(fc-match -f '%{file}' 'JetBrains Mono')" --ui "$(fc-match -f '%{file}' 'Inter:semibold')"
```

`--mono-weight` (default 400) and `--ui-weight` (default 600) set the weights. `--mono-name` and `--ui-name` are
only labels in the results. `--stand-in "<text>"` records that the files are stand-ins. `--smoke` runs one
sample of one configuration and writes to `/tmp`. Pass WOFF2, TTF, OTF or TTC files: `cmap.mjs` decodes WOFF2 (the
`cmap` and `name` tables, which WOFF2 never transforms), reads face 0 of a `.ttc` and rejects WOFF 1. The
weight goes to the `FontFace` descriptor and the canvas font string; that a variable font is drawn at the
requested weight is untested (the recorded run used static fonts). Cold timings are read at n = 20, where the nearest-rank
"p95" is the maximum; E11-S11 uses n ≥ 40.

On a host without Chromium's system libraries, set `LD_LIBRARY_PATH` to a directory that has them. This is
how the recorded run was made (`../E11-K01.md`, "Method").
