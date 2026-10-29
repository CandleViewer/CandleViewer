# E06 M0 findings report — custom chart engine and desktop shell

- **Every matrix figure here was measured on one host below the `06` §3.1 reference class** (§1): a budget
  met is conservative evidence, a budget missed is inconclusive and is re-measured on reference hardware;
  B10's memory peak and growth are inconclusive on that rule.
- Ticket: E06-T02 (#221), parent E06. Evidence: the E06-T01 matrix run merged at `bc40cc91`
  (`packages/chart-engine/bench/matrix/results/2026-10-29-win11-i7-8550u/`, raw `cv-matrix-report/1`
  JSON plus `SUMMARY.md`). Cited by ADR-0002 and ADR-0011 (their amendments are E06-T03, #222).
- Every matrix figure is inside a `m0-report` block, generated from those raw files by
  `packages/chart-engine/bench/matrix/m0-report.mjs` (§15); nothing in them is typed by hand. Prose outside
  the blocks points at a row instead of repeating a matrix figure (the unit suite checks this); numbers quoted
  from the spike documents (K03, K04, D03, Q02, E10-K01) are not matrix figures and cite their file and section.

## 1. Read this first: the hardware class and the evidence rule

**Every matrix figure in this report was measured on one host below the reference class**: an Intel Core
i7-8550U (4 cores / 8 threads), 16 GB RAM and Intel UHD Graphics 620 on Windows 11, against `06` §3.1's
6-core / 12-thread, 32 GB, GTX 1650 / Iris Xe class (machine row in §5). The orchestrator's ruling on #220
(2026-10-29 08:40Z, under the owner's delegation) sets the evidence rule: a budget **met** here is
conservative evidence that it holds on the reference class; a budget **missed** here is **inconclusive**,
recorded as such and re-measured on reference hardware (the owner's attended run is a post-GA confirmation
line, not a gate). The same ruling dropped the Tauri / WebView2 arm (§4). The raw reports'
`admissibleForAdrEvidence` flag is the harness's repetition-count rule only, not a machine-class judgement.

What the numbers are: frame time is the wall-clock cost of the scene step, a fixed real WebGL2 load
(`gl.finish()` included) and a 100-node DOM-mirror update, on the spike's harness page — not the production
engine, which does not exist yet. The K02–K04 scene classes model their GPU cost; that model output is kept
apart (§3.4). Sub-millisecond figures are quantised to the page's 0.1 ms timer; "< 0.1" means under it.

## 2. Executive verdict

<!-- m0-report:begin verdict -->
<!-- prettier-ignore-start -->
| #   | Verdict                                                                                                                                                                                                                                                                                                                                        | Traces to                             |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| V1  | **Custom engine: GO.** R0 exit criterion 4 (roadmap §4.3, ≥ 60 fps p50 and ≥ 55 fps p95 on the combined scene in Electron) **passes** (conservative, §1): B5 p50 0.20 ms, p95 0.50 ms, 15 draws. Adding the scene models' modelled B5 cost (6.39 ms, §3.4), which the headline excludes, gives about 6.9 ms: still within the 16.7 ms B5 gate. | §3.2, row "Electron"; §3.4 "Total"    |
| V2  | **ADR-0002's fallback trigger does not fire on the measured half**: B1, B3, B4 and B5 meet their p95 gates in both Chromium and Electron. The other half (M1 overrun) is a schedule fact.                                                                                                                                                      | §3.3, row "Trigger half 1"            |
| V3  | Both verdicts are **conservative** (met on a below-class host) and rest on a harness page, not the engine: E11 must re-establish them on the real engine (§10, §13).                                                                                                                                                                           | §1, §5                                |
| V4  | **Shell: Electron, confirmed.** ADR-0011 criteria 1–4 are not measured and are decided on criterion 5, which Tauri fails (E10-K01 §4). Electron has full WebGL2 capability parity.                                                                                                                                                             | §4; §5 capability rows                |
| V5  | **Inconclusive, re-measure:** B10 resident memory missed its soak-window peak gate and its growth gate read start to end (§3.5). Memory does not scale with GPU class the way frame time does, so E11 treats it as real.                                                                                                                       | §3.5, row "Electron"                  |
| V6  | **A hitch that p95 hides:** B5 has 114 frames over 33 ms (p99 81.60 ms) in every run, runtime and flag set — the 500 ms footprint rebuild (`SUMMARY.md` "B5 and R0 exit criterion 4"). M3 must chunk it.                                                                                                                                       | §3.2, column "Frames > 33 ms"; §10 M3 |
| V7  | The CI job (Chromium per PR, Electron nightly) records the matrix and never gates in R0 (roadmap §4.4 "not yet gating").                                                                                                                                                                                                                       | §12                                   |
<!-- prettier-ignore-end -->
<!-- m0-report:end -->

## 3. Results

### 3.1 Results matrix (B1–B10)

B6 and B8 are outside the E06-T01 matrix set. Gates are `26` §13; B10's frame gate is `06` §2 budget 1, the
load the B10 page runs (100k bars plus a 100 ms heatmap).

<!-- m0-report:begin results -->
<!-- prettier-ignore-start -->
**Electron (primary run)** — `electron-2026-10-29T08-59-53-274Z.json`; ms, medians over repetitions (p95: median of per-repetition p95, 06 §7.4).

| Scenario | Gate          | Reps | p50  | p95  | p99   | p95 per rep     | max    | Draws | Verdict |
| -------- | ------------- | ---- | ---- | ---- | ----- | --------------- | ------ | ----- | ------- |
| B1       | p95 ≤ 12 ms   | 3    | 0.10 | 0.20 | 0.30  | 0.2 / 0.2 / 0.3 | 0.90   | 4     | met     |
| B2       | p95 ≤ 14 ms   | 3    | 0.10 | 0.20 | 0.30  | 0.2 / 0.3 / 0.2 | 0.60   | 4     | met     |
| B3       | p95 ≤ 16 ms   | 3    | 0.20 | 0.30 | 0.40  | 0.4 / 0.3 / 0.3 | 1.70   | 3     | met     |
| B4       | p95 ≤ 10 ms   | 3    | 0.10 | 0.60 | 0.80  | 0.6 / 0.6 / 0.9 | 5.50   | 5     | met     |
| B5       | p95 ≤ 16.7 ms | 3    | 0.20 | 0.50 | 81.60 | 0.5 / 0.5 / 0.6 | 140.00 | 15    | met     |
| B10      | p95 ≤ 16.6 ms | 1    | 1.30 | 2.60 | 3.50  | 2.6             | 59.30  | 9     | met     |

| Scenario          | Gate                   | Figure                                                        | Verdict |
| ----------------- | ---------------------- | ------------------------------------------------------------- | ------- |
| B7 frame          | p95 ≤ 16.7 ms          | not recorded (the harness keeps decode and drop figures only) | n/a     |
| B7 decode, inline | p95 ≤ 4 ms, 0 dropped  | p95 < 0.1, 0 dropped, 0 duplicated, 3 reps                    | met     |
| B7 decode, worker | p95 ≤ 4 ms, 0 dropped  | p95 < 0.1, 0 dropped, 0 duplicated, 3 reps                    | met     |
| B9 cold init      | ≤ 900 ms (median of 3) | 7.00                                                          | met     |

**Headless Chromium (primary run)** — `chromium-2026-10-29T10-02-17-231Z.json`; ms, medians over repetitions (p95: median of per-repetition p95, 06 §7.4).

| Scenario | Gate          | Reps | p50  | p95  | p99    | p95 per rep     | max       | Draws | Verdict |
| -------- | ------------- | ---- | ---- | ---- | ------ | --------------- | --------- | ----- | ------- |
| B1       | p95 ≤ 12 ms   | 3    | 0.40 | 1.10 | 2.00   | 0.9 / 1.1 / 1.2 | 10.70     | 4     | met     |
| B2       | p95 ≤ 14 ms   | 3    | 0.30 | 1.10 | 1.70   | 1.1 / 1.1 / 1.2 | 7.00      | 4     | met     |
| B3       | p95 ≤ 16 ms   | 3    | 0.40 | 1.00 | 2.30   | 0.9 / 1.2 / 1.0 | 8.80      | 3     | met     |
| B4       | p95 ≤ 10 ms   | 3    | 0.30 | 1.40 | 2.90   | 1.7 / 1.4 / 1.3 | 28.40     | 5     | met     |
| B5       | p95 ≤ 16.7 ms | 3    | 0.50 | 3.50 | 336.40 | 3.6 / 2.8 / 3.5 | 538.70    | 15    | met     |
| B10      | p95 ≤ 16.6 ms | 1    | 1.20 | 4.70 | 12.60  | 4.7             | 632481.80 | 9     | met     |

| Scenario          | Gate                   | Figure                                                                               | Verdict |
| ----------------- | ---------------------- | ------------------------------------------------------------------------------------ | ------- |
| B7 frame          | p95 ≤ 16.7 ms          | not recorded (the harness keeps decode and drop figures only)                        | n/a     |
| B7 decode, inline | p95 ≤ 4 ms, 0 dropped  | p95 0.10, 0 dropped, 0 duplicated, 3 reps (`chromium-2026-10-29T10-59-08-627Z.json`) | met     |
| B7 decode, worker | p95 ≤ 4 ms, 0 dropped  | p95 0.10, 0 dropped, 0 duplicated, 3 reps (`chromium-2026-10-29T10-59-08-627Z.json`) | met     |
| B9 cold init      | ≤ 900 ms (median of 3) | 4.70                                                                                 | met     |
<!-- prettier-ignore-end -->
<!-- m0-report:end -->

The headless-Chromium arm renders with SwiftShader (the K01 pinned software-GL flags): it is the
shell-versus-engine attribution baseline, not the GPU. B9 is a JavaScript cold init over the generated fixture
plus the first GL draw, not a process cold start (that is `06` budget 10, E10-Q04). Secondary gates the matrix
harness does not measure — B2 LOD-change count, B3 text batching and text draw calls, B4 upload bytes and texture
memory, B9 SDF-atlas time — come from the K03 and K04 spikes (§6, §7) or are open (§11).

### 3.2 B5 and R0 exit criterion 4

<!-- m0-report:begin b5 -->
<!-- prettier-ignore-start -->
| B5 run                 | p50 ms (≤ 16.67) | p95 ms (≤ 16.7) | Draws (≤ 40) | p99 ms | Frames > 33 ms | max ms | Criterion 4 and B5 gates |
| ---------------------- | ---------------- | --------------- | ------------ | ------ | -------------- | ------ | ------------------------ |
| Electron               | 0.20             | 0.50            | 15           | 81.60  | 114            | 140.00 | PASS                     |
| Electron repeat        | 0.20             | 0.50            | 15           | 83.30  | 114            | 135.30 | PASS                     |
| Electron default flags | 0.20             | 0.60            | 15           | 83.00  | 114            | 143.60 | PASS                     |
| Chromium               | 0.50             | 3.50            | 15           | 336.40 | 114            | 538.70 | PASS                     |
<!-- prettier-ignore-end -->
<!-- m0-report:end -->

The "Frames > 33 ms" column is identical in every run, runtime and flag set: one frame per footprint rebuild
after warm-up (`scenes/b5-combined.mjs` rebuilds every 500 ms; `SUMMARY.md` "B5 and R0 exit criterion 4").
They are a scene (engine-side) cost, not a shell cost, and the B5 gate and criterion 4 are both p95 bars, so
they cannot see them (V6).

### 3.3 ADR-0002 fallback trigger

<!-- m0-report:begin trigger -->
<!-- prettier-ignore-start -->
| Gate           | Budget                        | Electron p95 ms | Chromium p95 ms |
| -------------- | ----------------------------- | --------------- | --------------- |
| B1             | p95 ≤ 12 ms                   | 0.20; met       | 1.10; met       |
| B3             | p95 ≤ 16 ms                   | 0.30; met       | 1.00; met       |
| B4             | p95 ≤ 10 ms                   | 0.60; met       | 1.40; met       |
| B5             | p95 ≤ 16.7 ms                 | 0.50; met       | 3.50; met       |
| Trigger half 1 | all four met in both runtimes | does not fire   | does not fire   |
<!-- prettier-ignore-end -->
<!-- m0-report:end -->

### 3.4 Per-stage attribution (`06` §4.3)

The harness measures two stages directly (DOM mirror and `texSubImage2D` upload); the rest of the headline is
not split (the page does not record `gl-load.mjs`'s submit / finish split — open item U4).

<!-- m0-report:begin stages -->
<!-- prettier-ignore-start -->
Measured (ms, medians over repetitions):

| Scenario | DOM mirror p95, Electron | DOM mirror p95, Chromium | Mirror vs its 1 ms slice (Electron / Chromium) | `texSubImage2D` median, Electron | `texSubImage2D` median, Chromium |
| -------- | ------------------------ | ------------------------ | ---------------------------------------------- | -------------------------------- | -------------------------------- |
| B1       | 0.20                     | 1.00                     | within / within                                | not recorded                     | not recorded                     |
| B2       | 0.20                     | 0.90                     | within / within                                | not recorded                     | not recorded                     |
| B3       | 0.20                     | 0.80                     | within / within                                | not recorded                     | not recorded                     |
| B4       | 0.20                     | 0.70                     | within / within                                | < 0.1                            | < 0.1                            |
| B5       | 0.20                     | 1.10                     | within / over                                  | < 0.1                            | < 0.1                            |
| B10      | 1.00                     | 1.40                     | within / over                                  | < 0.1                            | < 0.1                            |

Modelled per-stage cost of B5 (`modelledStageMs`; a scene-model output, not a measurement):

| Stage (06 §4.3)             | Electron | Chromium | Slice  | Note                      |
| --------------------------- | -------- | -------- | ------ | ------------------------- |
| Input handling              | 0.25     | 0.25     | ≤ 1    | within                    |
| Data-window recompute       | 0.00     | 0.00     | ≤ 2    | within                    |
| Candle geometry             | 2.21     | 2.21     | ≤ 2    | over slice (model output) |
| Footprint text and geometry | 0.87     | 0.97     | ≤ 4    | within                    |
| Heatmap upload              | 0.00     | 0.00     | ≤ 2    | within                    |
| Pane redraw                 | 2.39     | 2.39     | ≤ 2    | over slice (model output) |
| Overlay and order lines     | 0.32     | 0.32     | ≤ 1    | within                    |
| DOM-mirror sync (modelled)  | 0.00     | 0.00     | ≤ 1    | within                    |
| Composite and present       | 0.36     | 0.36     | ≤ 1.6  | within                    |
| Total                       | 6.39     | 6.49     | ≤ 16.6 |                           |
<!-- prettier-ignore-end -->
<!-- m0-report:end -->

The two modelled stages over their slice (candle geometry and pane redraw) are model constants, not measured
misses; M1 and M5 re-measure them (§10).

### 3.5 B10 30-minute soak

<!-- m0-report:begin b10 -->
<!-- prettier-ignore-start -->
| B10 run  | Frames | Frame p95 ms (gate ≤ 16.6)                            | Per-minute p95 ms | Frames > 33 ms    | Soak-window peak MB (≤ 600)               | Soak growth, start to end (≤ 5 %)                         | Soak growth, first to last third (≤ 5 %) | Whole-run peak MB (app metrics / OS sample) |
| -------- | ------ | ----------------------------------------------------- | ----------------- | ----------------- | ----------------------------------------- | --------------------------------------------------------- | ---------------------------------------- | ------------------------------------------- |
| Electron | 19740  | 2.60; met                                             | 1.8 to 3.1        | 2 (max 59.3)      | 1003; missed — inconclusive on this class | 747 to 859 = +15.0 %; missed — inconclusive on this class | 955 to 990 = +3.7 %; met                 | 1217 / 1378                                 |
| Chromium | 19740  | 4.70; met (run ended with `timeout after 2855000 ms`) | 2.9 to 5.9        | 47 (max 632481.8) | not attributable                          | not attributable                                          | not attributable                         | not attributable                            |
<!-- prettier-ignore-end -->
<!-- m0-report:end -->

Electron soak-window memory is the `app.getAppMetrics()` working-set sum, one sample per 15 s; the soak window
is the last 30 minutes of samples. The `26` §13 gate is "no monotonic growth beyond 5 % per 30 min", so the
table gives both readings: start to end (5-sample medians) and first to last third (medians of each 10-minute
third). The last column's first figure is the app-metrics peak over the whole run and its second the harness's
OS-sample `peakMb`; both fall before the soak (`SUMMARY.md` "B10"). The soak's shape is a warm-up step to a
plateau, flat for about 22 minutes, then a drop (`SUMMARY.md` "B10"), so it is not a monotonic climb — the
conservative reading still records the start-to-end miss, and the figure covers the whole harness page (the
100k-bar fixture, three scene models, the GL load, the mirror), not the engine. Chromium memory is not
attributable: the harness sums every `chrome` process and the host ran unrelated ones. The Chromium soak's
largest frame (its "max" in the row) is a SwiftShader stall in `gl.finish()`; it stretched the soak and
tripped the runner watchdog (the run error in its row), so its outlier count is not a runtime property.

### 3.6 Noise band (A/B/A) and Electron flag sets

<!-- m0-report:begin noise -->
<!-- prettier-ignore-start -->
| Scenario              | Electron `electron-2026-10-29T08-59-53-274Z.json` | Repeat `electron-2026-10-29T10-55-25-308Z.json` | Delta ms |
| --------------------- | ------------------------------------------------- | ----------------------------------------------- | -------- |
| B1                    | 0.20                                              | 0.20                                            | +0.00    |
| B2                    | 0.20                                              | 0.40                                            | +0.20    |
| B3                    | 0.30                                              | 0.40                                            | +0.10    |
| B4                    | 0.60                                              | 0.60                                            | +0.00    |
| B5                    | 0.50                                              | 0.50                                            | +0.00    |
| B9 (median cold init) | 7.00                                              | 2.90                                            | -4.10    |

B5 within the E06-Q01 band (0.46 %): **yes**; within ADR-0011's 10 %: **yes**.
<!-- prettier-ignore-end -->
<!-- m0-report:end -->

<!-- m0-report:begin flagsets -->
<!-- prettier-ignore-start -->
| Scenario              | `electron-tuned` (ms) | `electron-default` (ms) | Delta ms |
| --------------------- | --------------------- | ----------------------- | -------- |
| B1                    | 0.20                  | 0.30                    | +0.10    |
| B2                    | 0.40                  | 0.30                    | -0.10    |
| B3                    | 0.40                  | 0.30                    | -0.10    |
| B4                    | 0.60                  | 0.50                    | -0.10    |
| B5                    | 0.50                  | 0.60                    | +0.10    |
| B9 (median cold init) | 2.90                  | 2.80                    | -0.10    |
<!-- prettier-ignore-end -->
<!-- m0-report:end -->

The A/B/A gate passes on B5. Elsewhere the runs differ by whole 0.1 ms timer ticks in both directions, so
neither flag set wins at this resolution: no measurement gives a reason to change the shipped `tuned` set
(`apps/desktop/GPU_FLAGS.md`).

## 4. ADR-0011: the shell decision

| Criterion (ADR-0011)                                      | Status                                                                                                         |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| 1. B5 p95 in WebView2 within 10 % of Electron             | Not measured — decided on criterion 5 (ruling of 2026-10-29 08:40Z on #220)                                    |
| 2. No B10 outliers > 33 ms absent under Electron          | Not measured — decided on criterion 5                                                                          |
| 3. No progressive `texSubImage2D` degradation over 30 min | Not measured — decided on criterion 5 (Electron's per-minute upload median stays < 0.1 ms, `SUMMARY.md` "B10") |
| 4. WebGL2 capability parity                               | Not measured for WebView2 — decided on criterion 5 (Electron: full parity, §5)                                 |
| 5. Every shell responsibility has a working equivalent    | **Fails for Tauri**: GPU flag control and Playwright drivability need real redesign (`E10-K01.md` §4)          |

ADR-0011's rule — "if any criterion fails, Electron is confirmed" — therefore confirms Electron. The ADR's
"100–150 MB higher resident memory" claim has no second shell to compare with; Electron's own figures are §3.5.

## 5. Machine and version manifest

<!-- m0-report:begin manifest -->
<!-- prettier-ignore-start -->
Machine (hardware class only, identical in every report): Intel(R) Core(TM) i7-8550U CPU @ 1.80GHz, 8 logical CPUs, 16234 MB RAM, Intel(R) UHD Graphics 620 (driver 31.0.101.2135), win32 10.0.26300 x64.

Inputs: seed `20260928`, 100000 bars, fixture sha256 `dedf0e86781c31341d6e54e992ad0cfe85c2b65e25011becaff131eb77a9e579`, driver-script sha256 `d8ee23927a3106dc62ff75b7a87b4e05f4109975627e425cd8874af63634359d`, 3 repetitions × 20 s, soak 30 min.

| Report                                   | Runtime  | Flag set                                                                                    | Scenarios                | Electron | Chromium      | Node    | Playwright | WebView2                         | Run error                | sha256              |
| ---------------------------------------- | -------- | ------------------------------------------------------------------------------------------- | ------------------------ | -------- | ------------- | ------- | ---------- | -------------------------------- | ------------------------ | ------------------- |
| `electron-2026-10-29T08-59-53-274Z.json` | electron | electron-tuned                                                                              | B1 B2 B3 B4 B5 B7 B9 B10 | 45.0.0   | 156.0.8078.48 | 20.19.5 | -          | not applicable (no WebView2 arm) | none                     | `7d43a2434aeda140…` |
| `chromium-2026-10-29T10-02-17-231Z.json` | chromium | pinned-K01 (software GL; override with a real-GPU set on the reference machine, see README) | B1 B2 B3 B4 B5 B9 B10    | -        | 156.0.8078.4  | 20.19.5 | 1.64.1     | not applicable (no WebView2 arm) | timeout after 2855000 ms | `14c9780df733c5e5…` |
| `electron-2026-10-29T10-55-25-308Z.json` | electron | electron-tuned                                                                              | B1 B2 B3 B4 B5 B9        | 45.0.0   | 156.0.8078.48 | 20.19.5 | -          | not applicable (no WebView2 arm) | none                     | `ab745f7ccff653e1…` |
| `electron-2026-10-29T10-57-08-614Z.json` | electron | electron-default                                                                            | B1 B2 B3 B4 B5 B9        | 45.0.0   | 156.0.8078.48 | 20.19.5 | -          | not applicable (no WebView2 arm) | none                     | `c624b97f9a2a2ca7…` |
| `chromium-2026-10-29T10-59-08-627Z.json` | chromium | pinned-K01 (software GL; override with a real-GPU set on the reference machine, see README) | B7                       | -        | 156.0.8078.4  | 20.19.5 | 1.64.1     | not applicable (no WebView2 arm) | none                     | `d9c81b097570537d…` |

Flag sets: `electron-tuned` = `--enable-gpu-rasterization` `--disable-features=CalculateNativeWinOcclusion`; `pinned-K01 (software GL; override with a real-GPU set on the reference machine, see README)` = `--use-gl=angle` `--use-angle=swiftshader` `--disable-gpu-vsync` `--enable-webgl2` `--force-color-profile=srgb`; `electron-default` = no switches.

| Runtime  | WebGL renderer                                                                               | WebGL2 | `EXT_color_buffer_float` | R16F sampling | Instancing | OffscreenCanvas | WebGL2 in a worker (B7) | Max texture |
| -------- | -------------------------------------------------------------------------------------------- | ------ | ------------------------ | ------------- | ---------- | --------------- | ----------------------- | ----------- |
| electron | ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00005917) Direct3D11 vs_5_0 ps_5_0, D3D11)        | yes    | yes                      | yes           | yes        | yes             | yes                     | 16384       |
| chromium | ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) | yes    | yes                      | yes           | yes        | yes             | yes                     | 8192        |
<!-- prettier-ignore-end -->
<!-- m0-report:end -->

**Shelf life.** The figures belong to Electron 45 / Chromium 156, the listed driver and Node 20.19.5; a
Chromium or driver bump can move them, which is why the CI job (§12) keeps measuring. There is no WebView2
version to track: the WebView2 arm was dropped (§4). The raw files' sha256 values are pinned in `SUMMARY.md`.

**CI runner specification** (the class the CI baselines will come from, §12): GitHub-hosted `ubuntu-latest`,
x86-64, no GPU (4 vCPU / 16 GB at the time of writing; recorded in every CI report's manifest). Chromium renders
with the K01 pinned flags (ANGLE on SwiftShader); Electron runs under `xvfb-run` with the `tuned` flag set and
also gets software GL. These numbers compare only with baselines from the same class. **The hosted software-GL CI numbers are not
reference-hardware evidence (the committed matrix on `main` is); they are regression tracking only.** A dedicated GPU runner with
a pinned flag set (`26` §13) is E03-T14 / E11-T06's (U6).

## 6. Text strategy (E06-K03)

**Decision: SDF atlas.** In `E06-K03.md` "B3 results" the SDF arm meets B3 (p95 1.87 ms typical, 2.59 ms on a
27,381-glyph stress, text batching 0.52 / 0.97 ms, one text draw call); the Canvas-2D glyph cache fails the
≤ 2 text-draw-call gate structurally (one call per glyph, 15,689 calls) and, as modelled, p95 (~34 ms). The
K03 GPU costs are modelled and the Canvas-2D arm is a spot-check, not a measurement; the ranking rests on draw
calls. **O2 is closed** (`E06-K03.md` "O2 decision"): one 1024 × 1024 R8 atlas and a single 24 px size class,
holding 73 glyphs (`E06-K03.md` "Atlas"; `26` §16 O2). The matrix's real-WebGL2 B3 (§3.1) agrees with the verdict but does not render glyphs.

## 7. Heatmap (E06-K04)

- **Constant upload is proven by counter**: 11,264 B/s at 5 min, 1 h and 4 h trails and at 5× message rate
  (`E06-K04.md` "Experiments") — one column per 100 ms by construction. That is 11.0 of the 12 KB/s B4 budget:
  1 KB/s of headroom.
- **O3, coarse ring: provisionally 1 s** (14,400 columns = 4 h, 14.06 MB; 2 s saves only 0.5 KB/s), final at
  the real-GPU soak in M4 (`E06-K04.md` "O3"; `26` §16).
- **Per-symbol memory**: 16.06 MB of GPU texture per symbol plus an equal CPU shadow (`E06-K04.md`
  "Experiments").
- **Context loss**: recovery re-uploads 16,843,776 B from the CPU data model with no column lost (CPU model
  only). Raw WebGL lose / restore works in SwiftShader, but a lose immediately followed by restore did not
  recover (`E06-Q02.md` §5 C1, finding F1): the engine must serialise lost → restore.
- Price-origin shifts must be amortised: the coarse ring makes a vertical scroll 7× costlier than the fine ring
  (`E06-K04.md` "Experiments"). In the matrix, the `texSubImage2D` median stays under the 0.1 ms timer in every
  soak minute in both runtimes (§3.5 and `SUMMARY.md` "B10").

## 8. Accessibility cost (E06-D03)

The DOM mirror is part of the frame budget (`06` §4.3: ≤ 1 ms), so it is reported here, not in an appendix.

- **Measured in the matrix**: the harness's 100-node mirror update, a stand-in, not D03's structure. Its p95
  per scenario and runtime, and whether it stays within the 1 ms slice, are §3.4's "DOM mirror" columns.
- **D03's own measurement**, in headless Chromium (`docs/design/E06/E06-D03.md` §3 F14, §10 item 1): with
  bar-keyed row recycling a 30 bars/s pan costs 0.8 ms p95 at the default 60-row window (within 1 ms) and
  1.4 ms at the 200-row cap (over); a 10-bars-per-frame (600 bars/s) fling costs 1.4 ms at the 60-row window
  and 2.8 ms at the 200-row cap (both over). Per-cell mirroring is not affordable (F15). Cost is met by the `06` §4.4 degradation
  ladder and an opt-in cap, never by desyncing; the worker protocol implies one frame of mirror skew (F16).
- **Announcement cadence** (D5, `26` §12): one polite region, last-write-wins, `repeatWindow` 500 ms,
  `trailingFlush` ≤ 250 ms; US-CHART-008's ≤ 2/s holds.
- **LOD / mirror parity** (D7, `26` §12): the mirror never exposes less than the canvas draws at any LOD;
  `degraded-2d` limits footprint to L2 / L3 and the mirror carries the values (D8).
- **Pass criterion carried to E11**: D9's transferable row payload in the worker's `a11y` message joins this
  report's pass criterion (D03 §10 item 6). D03 §8 item 1 handed this ticket the Electron, reference-hardware,
  worker-rendering run; the matrix harness does not run D03's bench, so it is open item U9 (§11).

## 9. Compatibility (E06-Q02)

- **Swept**: only class S1 (software / ANGLE) in headless Chromium 153: SwiftShader default, `--disable-gpu`
  (still serves WebGL2), and `--disable-gpu --disable-software-rasterizer` (no WebGL2 → `degraded-2d`)
  (`E06-Q02.md` §1, §2). Detection must key on `getContext('webgl2') === null` and the renderer string, not
  flags (`E06-Q02.md` §3).
- **This matrix adds** two real configurations (§5): Electron 45 on ANGLE D3D11 / UHD 620 and Chromium 156 on
  SwiftShader — full capability parity in both, WebGL2 in a worker included.
- **Not run**: N1 (GTX 1650 class), I1 (Iris Xe), Edge, Firefox; G1–G3 deferred (E46 / owner QA)
  (`E06-Q02.md` §1), except that the Electron arm's UHD 620 partly covers G2 (Intel UHD class) for Electron.
- **`degraded-2d` delivers**: provisionally **not usable** for a 2,500-cell footprint at 60 fps (synthetic
  Canvas-2D p95 39–121 ms, `E06-Q02.md` §3); candle / axis-only scenes and footprint L2 / L3 are untested. The
  renderer itself does not exist yet (E11-T05).
- **Inline vs worker equivalence** cannot be tested until `RunMode` exists: E11 constraint C-Q02-1
  (`E06-Q02.md` §4).

## 10. What M1–M8 must budget

<!-- m0-report:begin budget -->
<!-- prettier-ignore-start -->
| M   | What the findings say to budget (evidence)                                                                                                                                                                                                                                                                                                                                                                                                                    |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | Re-baseline B1 / B2 on the real engine in the CI job (§12); record the `06` §4.3 stage split the harness lacks (U4); candle geometry was modelled at 2.21 ms against its 2 ms slice, over (§3.4). Capability probe and context-loss handling must serialise lost → restore (§7, F1).                                                                                                                                                                          |
| M2  | Worker + `RunMode.inline` with a shared LOD trace hook so Q02's equivalence protocol runs (C-Q02-1, §9); keep B7's frame p95 in the report cell (U3); the D9 mirror row payload (§8, U9). B9: 7.00 ms Electron / 4.70 ms Chromium against 900 ms (§3.1) — a JavaScript cold init over the generated fixture, not an engine or process cold start, so M2 re-measures it. Memory governor: B10's Electron page peaked at 1003 MB in the soak window (§3.5, V5). |
| M3  | Chunk the footprint rebuild across frames — the matrix shows a 500 ms rebuild costing up to 143.60 ms in Electron (§3.2 "max ms", V6) and K03 measured a 5.7 ms reformat (`E06-K03.md` "Reformat cost"); real WebGL2 B3 with glyphs, DPR 1.0 / 1.5 / 2.0 goldens, IndexedDB atlas ≤ 5 ms (`E06-K03.md` "What M3 must budget").                                                                                                                                |
| M4  | Upload headroom is 1 KB/s of 12 (§7, `E06-K04.md` "Experiments"); amortise price-origin shifts; confirm O3 at the real-GPU 4 h soak; 16.06 MB GPU per symbol (§7).                                                                                                                                                                                                                                                                                            |
| M5  | Pane redraw was modelled at 2.39 ms against its 2 ms slice, over (§3.4); B5 re-measured with real layers in Electron, ≤ 40 draws (15 today, §3.2).                                                                                                                                                                                                                                                                                                            |
| M6  | B5 with 50 real order lines; the overlay stage was modelled at 0.32 ms against its 1 ms slice, within (§3.4). Its order-line and position updates are never shed (`06` §4.4); the stage's drawing tools are not protected.                                                                                                                                                                                                                                    |
| M7  | B8 (not in the matrix): no M0 evidence; budget from `26` §13 only.                                                                                                                                                                                                                                                                                                                                                                                            |
| M8  | B10 memory re-measured on reference hardware (V5) and on the real engine; DOM-mirror cost at the 200-row cap and in a fling is over 1 ms (§8, U9); B6 (not in the matrix) has no M0 evidence.                                                                                                                                                                                                                                                                 |
<!-- prettier-ignore-end -->
<!-- m0-report:end -->

## 11. Open items and residual unknowns

O1–O5 are `26` §16's. U1–U9 are new; each has an owner and a resolution path.

| #   | Item                                                                                 | Owner                             | Resolution path                                                                                                                                                                     |
| --- | ------------------------------------------------------------------------------------ | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| O1  | Electron vs Tauri                                                                    | Architect                         | Decided on criterion 5 here (§4); closed by E06-T03 (#222)                                                                                                                          |
| O2  | SDF atlas size / glyph set                                                           | Chart-engine lead + design system | Closed by E06-K03; M3 re-confirms on a real context (E11-S11)                                                                                                                       |
| O3  | Coarse-ring resolution                                                               | Chart-engine lead                 | Provisionally 1 s (§7); M4 real-GPU soak                                                                                                                                            |
| O4  | Indicator compute: worker vs backend                                                 | Architect + backend lead          | Unchanged; M5 benchmark (`26` §16)                                                                                                                                                  |
| O5  | Colour-blind-safe default palette                                                    | Design system + a11y              | Unchanged; M8 a11y pass                                                                                                                                                             |
| U1  | Every matrix figure is from a below-class host                                       | Owner / QA                        | Re-measure on reference hardware (post-GA confirmation line, ruling of 2026-10-29)                                                                                                  |
| U2  | B10 memory peak and growth missed (inconclusive)                                     | Chart-engine lead                 | Re-measure with the real engine on reference hardware (E11-S15, E11-Q03)                                                                                                            |
| U3  | B7 frame p95 not recorded (`summariseCell` drops it)                                 | Chart-engine lead                 | Keep `workerFrameP95Ms` in the cell when E11-T06 promotes the harness                                                                                                               |
| U4  | Stage split beyond mirror and upload not recorded                                    | Chart-engine lead                 | Record `gl-load.mjs`'s submit / finish split and engine stage markers (E11-T07, E11-T06)                                                                                            |
| U5  | SwiftShader stalls (B7 hang, the B10 soak's largest frame, §3.5) on the Chromium arm | QA                                | B7 runs nightly only (Electron), not per PR on SwiftShader; the harness watchdog fix (a timeout for the worker storm) and B7's return to the per-PR set are E11-T06 (#449)          |
| U6  | No GPU in CI; hosted-runner numbers are software GL                                  | Architect                         | Dedicated GPU runner with a pinned flag set: E03-T14 / E11-T06                                                                                                                      |
| U7  | Q02 hardware cells (N1, I1, Edge, Firefox, G1–G3) and the `degraded-2d` renderer     | QA                                | E11-Q07 (#519) matrix charter; E11-T05 (#522) renderer                                                                                                                              |
| U8  | B5 co-tenancy variant (dev stack up) not run                                         | Chart-engine lead                 | Run once the dev stack and the real engine exist (E11-Q03)                                                                                                                          |
| U9  | D03 §8 item 1: the mirror bench in Electron on reference hardware, worker rendering  | Chart-engine lead + a11y          | E11-S13 (#520) runs it with the D9 `a11y` payload end to end; pass is p95 ≤ 1 ms on a pan at the 60-row window; the 200-row cap is sized from that run; E11-Q03 (#445) signs it off |

## 12. The CI benchmark job

`.github/workflows/perf-engine-matrix.yml`, recording only, not a required check:

- **Per PR** touching `packages/chart-engine/**`: headless Chromium, K01 pinned flags, B1 B2 B3 B4 B5 B9,
  3 repetitions × 20 s on the 100k-bar M0 fixture (no B7 per PR, since it stalls on SwiftShader, U5; no 30-minute soak per PR).
- **Nightly (02:41 UTC) and on dispatch**: Electron with the `tuned` flag set under `xvfb-run`, the full set
  including the 30-minute B10 soak.
- `bench/matrix/ci-compare.mjs` writes the comparison with `bench/matrix/baselines/<runtime>-ubuntu-latest.json`
  to the job summary (flagged at > 5 %, `06` §7.4, and ≥ 0.2 ms, this job's two-tick floor for the 0.1 ms timer, §1) and exits 0 on a regression; no report, an invalid
  report or a harness run error exits 1, so a failure to run is a red job. Report JSON and summary are uploaded.
- These are regression-tracking numbers only, never reference-hardware evidence (§5).
- B7's SwiftShader stall (U5) is why B7 left the per-PR set: its first per-PR run hung until the harness
  budget expired. If a stall ever reaches the nightly Electron run, the job goes red: a failure to run
  surfaced by design, not a regression, and the job is not required.
- The page can also post every cell and then never send `/done` (seen on SwiftShader at context teardown,
  after the last cell): the driver then finishes 30 s after the last requested cell (`DONE_GRACE_MS`,
  `bench/matrix/matrix-lib.mjs`) instead of waiting out its budget. The driver script hash is unchanged.
- Repetitions and median-of-p95 are the harness's rules (E06-K01), inherited, not restated. No fixture or flag
  is fetched at run time; the fixture is generated from the committed seed.
- **Baselines** move only by a reviewed PR with a rationale, from a CI artefact of `main` on the same runner
  class — policy in `packages/chart-engine/README.md`. The first Chromium baseline is taken from this job's
  first run on `main` (a `workflow_dispatch` on `main`: the Chromium job runs on PRs and on dispatch, never on a push) and the first Electron baseline from its first green nightly on `main`, each committed by
  a follow-up PR; until then the job records "no baseline yet" for that runtime. Making it gating is E11-T06 (#449).

## 13. Follow-ups (E11, E10)

No new tickets (filing freeze): after merge each existing ticket gets a comment citing the sections here.

| Ticket                                   | Cite                      | What it inherits                                                         |
| ---------------------------------------- | ------------------------- | ------------------------------------------------------------------------ |
| E11-T01 (#337) API surface               | §2, §10                   | The verdict and the per-milestone budget table                           |
| E11-S01 (#333) frame scheduler           | §3.4, §10 M1              | Stage slices; record the stage split (U4)                                |
| E11-S02 (#334) WebGL2 backend            | §7 (F1), §9, §10 M1       | Serialise lost → restore; capability probe keyed on renderer string      |
| E11-T02 (#338) worker and inline         | §9, §10 M2                | C-Q02-1 `RunMode` + LOD trace hook; B7 frame p95 (U3)                    |
| E11-S11 (#336) SDF text                  | §6, §10 M3                | SDF decision, O2 atlas, reformat chunking                                |
| E11-S12 (#418) LOD                       | §3.2, §10 M3              | The footprint-rebuild hitch (V6)                                         |
| E11-S13 (#520) DOM mirror                | §8, §10 M8, U9            | Mirror cost at the cap and in a fling; D9 payload; D03's Electron run    |
| E11-S15 (#448) memory governor           | §3.5, §10 M2 / M8, U2     | B10 memory miss                                                          |
| E11-T05 (#522) `degraded-2d`             | §9                        | Provisional "not usable" at 2,500 cells; detection rule                  |
| E11-T06 (#449) required bench check      | §5, §12, U3, U4, U6       | The recording job, baselines policy, GPU runner                          |
| E11-Q03 (#445) baselines sign-off        | §3, §11 U1 / U2 / U8 / U9 | Reference-hardware re-measure                                            |
| E11-Q07 (#519) GPU / runtime charter     | §9, U7                    | The Q02 cells not run                                                    |
| E10-Q04 (#303) cold start                | §3.1 (B9 note)            | B9 is not a process cold start; budget 10 is E10-Q04's                   |
| E10-Q02 (#301) Playwright-Electron suite | §3.6, §5, §12             | Keep the `tuned` flag set; Electron runs headless in CI under `xvfb-run` |

E10's shell hardening (E10-T02 #236, E10-X02 #307, both closed) gets no follow-up: the matrix ran the hardened
shell and produced no hardening finding beyond `SUMMARY.md` anomaly 6, three cosmetic CSP `style-src` notices
from the harness page's inline styles.

## 14. Risk register (`32-risk-register.md`)

The ticket's labels map to the register's own ids by subject: ticket "R2 render performance" = **RSK-001**
(re-scored L3/I5 = 15 → L2/I5 = 10, Critical → High); ticket "R8 browser / GPU compatibility" = **RSK-003**
(L3/I3 = 9 → L2/I3 = 6, Medium); ticket "R10 key person" = **RSK-037** (score unchanged; this report, its
generator and the CI job are the transferable artefact). Each entry carries a dated "Review" line with the
evidence.

## 15. Regenerating this report

From `packages/chart-engine`: `node bench/matrix/m0-report.mjs` rewrites the generated blocks;
`node bench/matrix/m0-report.mjs --check` fails when a block differs from a fresh render (the unit suite runs
it, and also fails if prose outside the blocks, here or in the E06-T02 review lines of `32`, repeats a
generated matrix figure). The script validates every raw report first (schema, machine descriptor, versions, ≥ 3 repetitions per
frame cell) and keeps hardware class only: host, user and path fields are dropped or redacted.
