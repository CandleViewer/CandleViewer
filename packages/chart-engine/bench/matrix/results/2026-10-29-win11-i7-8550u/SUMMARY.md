# E06-T01 measurement matrix: headless-Chromium and Electron arms, 2026-10-29 (below-class host)

**Hardware class: below the reference class.** Every figure in this directory was measured on one
Windows 11 host: Intel Core i7-8550U (4 cores / 8 threads, 1.8 GHz base), 16 GB RAM, Intel UHD
Graphics 620 (driver 31.0.101.2135), Windows 11 Pro build 26300, Balanced power plan on AC power.
That is below the reference class of `docs/plan/06-performance-and-load-standard.md` §3.1 (6 cores /
12 threads, 32 GB, GTX 1650 / Iris Xe class). The evidence rule comes from the orchestrator ruling
on #220 (issue comment of 2026-10-29 08:40Z, made under the owner's 07:05Z delegation). A budget
**met** here is conservative evidence that it holds on the reference class. A budget **missed** here
is **inconclusive**: it is recorded as such and re-measured on reference hardware, and the owner's
attended run becomes a post-GA confirmation line. The same ruling dropped the Tauri / WebView2 arm,
because ADR-0011 is decided on criterion 5. The evidence for criterion 5 is the E10-K01 spike
(`docs/plan/spikes/E10-K01.md`, appended to ADR-0011): two of the eight shell responsibilities, GPU
flag control and Playwright drivability, would need real redesign under Tauri. ADR-0011 criteria
1-4 therefore read "not measured, decided on criterion 5".

**The `admissibleForAdrEvidence` flag.** In the raw reports this flag is the harness's
repetition-count rule only (`bench/matrix/matrix-lib.mjs`, `summariseCell`). It is `true` for 3 or
more repetitions and always `true` for the once-per-runtime B10 soak. It takes no machine-class
input, so it reads `true` on every frame cell here. The report schema (`cv-matrix-report/1`) has no
note field, and none was invented. The raw files are committed byte-for-byte as the harness wrote
them (sha256 below), so the ruling is cited here and in the PR body instead. Read the flag together
with the hardware-class statement above: **these figures are not reference-class ADR evidence.**

How to read the numbers: frame time is the wall-clock time of the scene step, the real WebGL2 load
(`page/gl-load.mjs`, with `gl.finish()`) and the DOM-mirror update. The K02-K04 scene classes
**model** their GPU cost. That modelled cost is recorded separately (`modelledStageMs`) and is not
part of the headline (README, "How the numbers are produced"). Every sub-millisecond figure is
quantised to the page's 0.1 ms `performance.now()` resolution, so a decode or upload median of
`0.000` means "under 0.1 ms".

## Runs

The quiet-machine gate took three `Win32_Processor` `LoadPercentage` samples 10 s apart and
started a run only when all three were under 40 %. A failed gate became a rolling window of three
samples (a CIM error counted as "not quiet"). Every run used seed `20260928`, the 100,000-bar M0
fixture, 3 repetitions, 20 s per repetition and a 30-minute B10 soak.

| #   | Report                                   | Arm and flag set                                          | Scenarios                | UTC                 | Gate wait                        | Outcome                                                                    |
| --- | ---------------------------------------- | --------------------------------------------------------- | ------------------------ | ------------------- | -------------------------------- | -------------------------------------------------------------------------- |
| 1   | `electron-2026-10-29T08-59-53-274Z.json` | Electron (primary), `electron-tuned`                      | B1 B2 B3 B4 B5 B7 B9 B10 | 08:59:50 - 09:31:26 | none (3 / 9 / 9 %)               | exit 0                                                                     |
| -   | none written                             | Chromium attempt 1, `pinned-K01`                          | all eight                | 09:38:31 - 09:59:04 | 3 min 10 s (09:35:04 - 09:38:14) | aborted: B7 stalled for 17+ min (anomaly 2)                                |
| 2   | `chromium-2026-10-29T10-02-17-231Z.json` | Chromium (primary), `pinned-K01`                          | B1 B2 B3 B4 B5 B9 B10    | 10:02:16 - 10:50:43 | about 1.5 min (after the abort)  | exit 1, `runError: timeout after 2855000 ms`, B10 cell present (anomaly 3) |
| 3   | `electron-2026-10-29T10-55-25-308Z.json` | Electron repeat (A/B/A), `electron-tuned`                 | B1 B2 B3 B4 B5 B9        | 10:55:25 - 10:55:53 | 2 min 36 s (10:52:31 - 10:55:07) | exit 0                                                                     |
| 4   | `electron-2026-10-29T10-57-08-614Z.json` | Electron control, `electron-default`                      | B1 B2 B3 B4 B5 B9        | 10:57:06 - 10:57:43 | none (12 / 6 / 8 %)              | exit 0                                                                     |
| 5   | `chromium-2026-10-29T10-59-08-627Z.json` | Chromium B7 re-run, `pinned-K01`                          | B7                       | 10:59:08 - 11:00:21 | 44 s (10:58:08 - 10:58:52)       | exit 0                                                                     |
| -   | `adr-0011-table.md`                      | harness summary (`compare-matrix.mjs` on reports 1 and 2) | -                        | -                   | -                                | exit 0, "Comparable: yes"                                                  |

Flag sets, verbatim from the manifests:

- `electron-tuned`: `--enable-gpu-rasterization`, `--disable-features=CalculateNativeWinOcclusion`.
- `electron-default`: no switches.
- `pinned-K01 (software GL; override with a real-GPU set on the reference machine, see README)`:
  `--use-gl=angle`, `--use-angle=swiftshader`, `--disable-gpu-vsync`, `--enable-webgl2`,
  `--force-color-profile=srgb`.

The ordering was A/B/A: Electron, then Chromium, then the Electron repeat. The flag-set control ran
straight after the repeat so that both share one thermal state.

## Medians of p95, scenario by runtime

These are medians of the per-repetition p95 (06 §7.4), in ms. The Electron column is report 1. The
Chromium column is report 2, with B7 from report 5. Budgets are the p95 gates in
`docs/plan/26-chart-engine-design.md` §13. The Chromium arm renders with SwiftShader (software GL,
the K01 pinned flags), not the real GPU: it is the shell-versus-engine baseline (README).

| Scenario                                            | Budget                         | Electron (tuned) | Verdict | Chromium (K01) | Verdict                        |
| --------------------------------------------------- | ------------------------------ | ---------------- | ------- | -------------- | ------------------------------ |
| B1: 100k candles, continuous pan                    | p95 ≤ 12 ms                    | 0.20             | met     | 1.10           | met                            |
| B2: 100k candles, zoom sweep                        | p95 ≤ 14 ms                    | 0.20             | met     | 1.10           | met                            |
| B3: footprint, 2,500 cells with text                | p95 ≤ 16 ms                    | 0.30             | met     | 1.00           | met                            |
| B4: heatmap, 100 ms columns, panning                | p95 ≤ 10 ms                    | 0.60             | met     | 1.40           | met                            |
| B5: combined scene                                  | p95 ≤ 16.7 ms                  | 0.50             | met     | 3.50           | met                            |
| B7: live update storm                               | frame p95 ≤ 16.7 ms            | not recorded     | n/a     | not recorded   | n/a                            |
| B9: cold init to first frame (median of 3, not p95) | ≤ 900 ms                       | 7.00             | met     | 4.70           | met                            |
| B10: 30-min soak, frame p95 (1 run)                 | p95 ≤ 16.6 ms (06 §2 budget 1) | 2.60             | met     | 4.70           | met (soak stalled once, 632 s) |

Per-repetition p95 (ms):

- Electron: B1 0.2 / 0.2 / 0.3, B2 0.2 / 0.3 / 0.2, B3 0.4 / 0.3 / 0.3, B4 0.6 / 0.6 / 0.9, and
  B5 0.5 / 0.5 / 0.6.
- Chromium: B1 0.9 / 1.1 / 1.2, B2 1.1 / 1.1 / 1.2, B3 0.9 / 1.2 / 1.0, B4 1.7 / 1.4 / 1.3, and
  B5 3.6 / 2.8 / 3.5.

Draw calls are the same in both runtimes: B1 4 (secondary gate ≤ 8: met), B2 4, B3 3, B4 5, B5 15
and B10 9.

Notes on the table:

- **B7:** the harness keeps decode and drop figures only. `summariseCell` drops the per-repetition
  `workerFrameP95Ms` the page computes, so B7's frame gate has no figure in the committed artefacts.
- **B9:** this is a JavaScript cold init over the already-generated fixture plus the first GL draw.
  It is not a process cold start (README, "Known limitations").
- **B10:** §13 gives B10 memory gates only (below). The frame row uses 06 §2 budget 1, whose load is
  100k bars plus a heatmap updating every 100 ms, which is what the B10 page runs.

## B5 and R0 exit criterion 4

| B5 figure                            | Electron 1 | Electron 3 (repeat) | Electron 4 (default flags) | Chromium 2 | Budget                                                         | Verdict     |
| ------------------------------------ | ---------- | ------------------- | -------------------------- | ---------- | -------------------------------------------------------------- | ----------- |
| p50 (ms)                             | 0.20       | 0.20                | 0.20                       | 0.50       | ≤ 16.67 ms, at least 60 fps (roadmap §4.3, criterion 4)        | met         |
| p95, median of 3 (ms)                | 0.50       | 0.50                | 0.60                       | 3.50       | ≤ 16.7 ms (B5 gate); ≤ 18.18 ms, at least 55 fps (criterion 4) | met         |
| draw calls                           | 15         | 15                  | 15                         | 15         | ≤ 40 (B5 gate)                                                 | met         |
| p99 (ms)                             | 81.60      | 83.30               | 83.00                      | 336.40     | none                                                           | observation |
| frames over 33 ms (3 × 1,140 frames) | 114        | 114                 | 114                        | 114        | none                                                           | observation |
| max (ms)                             | 140.00     | 135.30              | 143.60                     | 538.70     | none                                                           | observation |

**R0 exit criterion 4 (roadmap §4.3, stated in Electron): PASS.** Electron B5 measured p50 0.20 ms,
p95 0.50 ms and 15 draw calls. On this class that is conservative evidence, and `adr-0011-table.md`
gives the same verdict. The composition is from the report: 3 indicator series, 50 order lines, the
layers A (bars and LOD), B (footprint and SDF), C (heatmap ring), the indicators and the order
lines, 368 visible bars, and 1,104 indicator points per frame.

**ADR-0002's fallback trigger.** The binding trigger has two halves. The first is spike S1 (M0)
failing its exit criteria: 100k candles, 2,500 footprint text cells and a 100 ms heatmap at the
documented p95 frame times, in both Chromium and Electron. Those map to B1 (≤ 12 ms), B3
(≤ 16 ms) and B4 (≤ 10 ms), plus B5 combined (≤ 16.7 ms). All four are met in both runtimes, so on
this evidence that half does not fire (conservative, since the host is below class). The second
half, M1 overrunning its 6-engineer-week estimate by more than 50 %, is a schedule fact, not a
measurement.

**A hitch that p95 does not see.** Each repetition has 1,140 measured frames, and 114 is 3 × 38.
That matches the number of 500 ms footprint rebuilds after the 60-frame warm-up:
`scenes/b5-combined.mjs` runs one every 500 ms, which gives 40 per 20 s repetition, 2 of them
inside the warm-up. The count is identical in all four B5 runs, in both runtimes and with both flag
sets, so these are almost certainly the rebuild frames. Each takes 33-144 ms in Electron and up to
539 ms in Chromium. They are 3.3 % of frames, so p95 (and with it the B5 gate and criterion 4)
cannot see them, while p99 does. They appear in every runtime, so under the ticket's attribution
rule this is a scene (engine-side) cost, not a shell cost. It is flagged for E06-T02 (#221).

**Per-stage attribution.** The harness measures two stages directly. The DOM mirror's p95 is
0.20 ms in Electron and 1.10 ms in Chromium (the §4.3 slice is ≤ 1 ms). The `texSubImage2D`
column-upload median is under 0.1 ms (slice ≤ 2 ms). The rest of the headline is not split:
`gl-load.mjs` returns a submit/finish split, but the page does not record it.

The scene models also write per-stage costs into `modelledStageMs`. These are not measurements
(mostly model constants, with small measured CPU parts), and the table sets them against the 06
§4.3 slices:

| Stage (06 §4.3)             | B5 modelled ms (Electron / Chromium) | §4.3 slice |
| --------------------------- | ------------------------------------ | ---------- |
| Input handling              | 0.25 / 0.25                          | ≤ 1        |
| Data-window recompute       | 0.00 / 0.00                          | ≤ 2        |
| Candle geometry             | 2.21 / 2.21                          | ≤ 2        |
| Footprint text and geometry | 0.87 / 0.97                          | ≤ 4        |
| Heatmap upload              | 0.00 / 0.00                          | ≤ 2        |
| Pane redraw (3 indicators)  | 2.39 / 2.39                          | ≤ 2        |
| Overlay and order lines     | 0.32 / 0.32                          | ≤ 1        |
| Composite and present       | 0.36 / 0.36                          | ≤ 1.6      |
| Total                       | 6.39 / 6.49                          | ≤ 16.6     |

Two modelled stages go over their slice: candle geometry (2.21 against 2 ms) and pane redraw (2.39
against 2 ms). These are model outputs, flagged for #221, not measured misses.

## B7: decode p95 and dropped messages

Each mode ran 3 repetitions of 10 s at 120 messages/s (20 messages/s × 6 stores), 1,200 messages
per repetition. The decode p95 below is the median over the repetitions; drops and duplicates are
summed. Inline and worker are summarised separately and never pooled.

| Mode                      | Electron decode p95 | Drops | Duplicates | Chromium decode p95 | Drops | Duplicates | Budget                       | Verdict (E / C) |
| ------------------------- | ------------------- | ----- | ---------- | ------------------- | ----- | ---------- | ---------------------------- | --------------- |
| inline (`RunMode.inline`) | under 0.1 ms        | 0     | 0          | 0.10 ms             | 0     | 0          | decode p95 ≤ 4 ms, 0 dropped | met / met       |
| worker (OffscreenCanvas)  | under 0.1 ms        | 0     | 0          | 0.10 ms             | 0     | 0          | decode p95 ≤ 4 ms, 0 dropped | met / met       |

WebGL2 on an OffscreenCanvas inside the worker worked in both runtimes
(`offscreenWebgl2InWorker: true`). The preamble field `capabilities.offscreenCanvasWorker` reads
`false` in every report because the page never fills it in. The B7 worker figure is the measured
value.

## B10: 30-minute soak

| Figure                            | Electron (report 1)                                                              | Chromium (report 2)                                                           | Budget                                                                  | Verdict (E / C)                               |
| --------------------------------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------- |
| frames measured                   | 19,740                                                                           | 19,740                                                                        | -                                                                       | -                                             |
| frame p95                         | 2.60 ms (per minute 1.8-3.1)                                                     | 4.70 ms (per minute 2.9-5.9)                                                  | ≤ 16.6 ms (06 §2 budget 1)                                              | met / met (Chromium soak stalled once, 632 s) |
| frames over 33 ms                 | 2 (minute buckets 7 and 14), max 59.3 ms                                         | 47 across 18 of 30 minute buckets, one of them the 632 s stall (632,481.8 ms) | none per runtime (ADR-0011 criterion 2 compares WebView2 with Electron) | observation                                   |
| peak resident memory, soak window | 1,003 MB                                                                         | not attributable                                                              | peak ≤ 600 MB (26 §13)                                                  | missed (inconclusive on this class) / n/a     |
| growth over the soak              | start to end +15.0 % (747 to 859 MB); first to last third +3.7 % (955 to 990 MB) | not attributable                                                              | no monotonic growth beyond 5 % per 30 min (26 §13)                      | missed (inconclusive on this class) / n/a     |
| `texSubImage2D` median per minute | under 0.1 ms in all 30 minutes                                                   | under 0.1 ms in all 30 minutes                                                | ADR-0011 criterion 3 (moot)                                             | n/a                                           |

**Electron memory.** The source is the `app.getAppMetrics()` working-set sum over every Electron
process, sampled every 15 s, with the soak window taken as the last 120 samples. The start and end
figures are 5-sample medians. The whole-run peaks are 1,217 MB (app metrics) and 1,378 MB (OS
sample), the harness's `peakMb`. Both fall in the run's first minute, not in the soak. In that
minute the page generates and hashes the fixture (it serialises to 289,533,856 characters) and
then runs B1-B5.

The soak itself has this shape:

1. 701 MB at the start.
2. A climb to a 978-992 MB plateau by about minute 7.
3. Flat for about 22 minutes.
4. A drop to about 860 MB in the last 75 s.

That is a warm-up step, not a monotonic climb. Read start to end, though, it is over 5 %, so it is
recorded as missed. The figure covers the whole harness page (the 100k-bar fixture, three scene
models, the GL load and the DOM mirror), so it is not an engine-only number. Memory does not scale
with CPU or GPU class the way frame time does, so #221 should look at this miss rather than put it
down to hardware.

**Chromium memory.** The harness sums the OS working set of every process named `chrome`,
`headless_shell` or `chrome-headless-shell`. This host had 8 unrelated `chrome` processes (about
518 MB) running throughout, so the Chromium `peakMb` (1,837) cannot be attributed to the run.

**Outliers.** Minute buckets are the harness's 0-based `soak[].bucket` index, so bucket 7 is the
eighth minute of the soak. Both Electron outliers (buckets 7 and 14) fall before the co-tenant
window of anomaly 1 (buckets 17-28), which has none. The Chromium count of 47 already includes the
632.5 s frame: `frame-stats.mjs` counts every frame over 33 ms, and the bucket sum equals the
cell's `outliers33`. That stall stretched the Chromium soak (anomaly 3), so its outliers cannot be
cleanly attributed to the runtime.

## Noise-band sanity gate (A/B/A)

| Scenario              | Electron 1 | Electron 3 (repeat) | Delta                    |
| --------------------- | ---------- | ------------------- | ------------------------ |
| B1                    | 0.20       | 0.20                | 0                        |
| B2                    | 0.20       | 0.40                | +0.20 ms (2 timer ticks) |
| B3                    | 0.30       | 0.40                | +0.10 ms (1 tick)        |
| B4                    | 0.60       | 0.60                | 0                        |
| **B5**                | **0.50**   | **0.50**            | **0.0 %**                |
| B9 (median cold init) | 7.00       | 2.90                | -4.10 ms                 |

The runbook's gate compares the two Electron runs' B5 medians of p95. They are equal (0.0 %), so
the gate **passed**: that is inside both the documented run-to-run band (E06-Q01 §3: 0.46 %) and
ADR-0011's 10 % threshold. The sub-millisecond scenarios differ by whole 0.1 ms timer ticks (B2's
0.20 to 0.40 ms is +100 %), so at this resolution the band means something only where values are
equal or large. Cold init varies by nature (E06-Q01 §3).

## Flag sets, for E10

| Scenario              | `electron-tuned` (report 3) | `electron-default` (report 4) |
| --------------------- | --------------------------- | ----------------------------- |
| B1                    | 0.20                        | 0.30                          |
| B2                    | 0.40                        | 0.30                          |
| B3                    | 0.40                        | 0.30                          |
| B4                    | 0.60                        | 0.50                          |
| B5                    | 0.50                        | 0.60                          |
| B9 (median cold init) | 2.90                        | 2.80                          |

Neither flag set wins on this host. Every frame-time difference is one 0.1 ms timer tick, and they
go both ways. For E10: no measurement here gives a reason to change the shipped `tuned` set
(`apps/desktop/GPU_FLAGS.md`), so keep it. Picking a performance winner is inconclusive at this
resolution and on this class.

## Run conditions

**Toolchain.**

- Node 20.19.5, the repo's `.nvmrc`. The host's default Node 20.14.0 is below the `engines`
  floor, so an OpenJS-signed portable Node 20.19.5 was put first on PATH.
- pnpm 12.5.1, the `packageManager` pin. The harness manifest has no pnpm field, so it is recorded
  here.
- Playwright 1.64.1 with its Chromium 156.0.8078.4 headless shell.
- Electron 45.0.0, which runs Chromium 156.0.8078.48.

The renderers were ANGLE D3D11 on the UHD 620 for Electron, and ANGLE on SwiftShader (Vulkan,
Subzero) for Chromium. Both reported WebGL2, `EXT_color_buffer_float`, R16F, instancing and
OffscreenCanvas.

**Inputs.** These are identical in all five reports, and `compare-matrix.mjs` reports "Comparable:
yes":

- seed `20260928` (seed32 `2904068074`) and 100,000 bars;
- fixture sha256 `dedf0e86781c31341d6e54e992ad0cfe85c2b65e25011becaff131eb77a9e579` (FNV-1a
  `7716744d`);
- driver-script sha256 `d8ee23927a3106dc62ff75b7a87b4e05f4109975627e425cd8874af63634359d`.

**Code.** The worktree is `origin/main` at `85edd514e`. The engine, the scenes, the budgets and the
harness are unchanged. The README's prerequisites were followed, and `--dry-run` passed for both
runtimes: the B5 composition has 3 indicators and 50 order lines, at most 15 modelled draws, and
the B7 logic had 0 drops.

**Host.** The machine was on the Balanced power plan. The runbook asks for High performance, but a
shared host's power settings were not changed. It ran on AC power, with about 5.8 GB of RAM free at
the start. The co-tenants were:

- the Claude Desktop agent host: about 2.3 GB, and about 0.3 of a core on average;
- 8 `chrome` processes: about 518 MB.

There was no WSL VM and no Docker, so the dev stack was down.

## Anomalies

1. **A co-tenant CPU spike during the Electron soak.** From 09:18:41Z until 09:29:53Z at the
   latest, another session's `git grep` ran a pathological regex on about 6 cores. Its 50 s
   timeout did not stop the native `git.exe`. It was not ours, so it was left running. It overlaps
   soak minute buckets 17-28 (0-based). Those buckets have no outliers, and the per-minute p95
   stays between 1.8 and 3.1 ms.
2. **Chromium attempt 1 stalled in B7.**
   - Attempt 1 started at 09:38:31Z. B1-B5 completed, but B7 never did.
   - The renderer, which hosts the page and its B7 worker, used 0.00 CPU-s over 30 s while the
     SwiftShader GPU process ran on about 5 cores. The page's worker storm has no timeout.
   - The runner writes its report only at the end, and its watchdog would not have fired until
     about 10:27Z.
   - Attempt 1 was stopped at 09:59Z (our own processes only), and its B1-B5 results were never
     written.
   - B1-B5, B9 and B10 were re-run (report 2), then B7 alone (report 5). B7 completed normally in
     73 s, so the stall is intermittent, not deterministic.
3. **A 632-second frame in the Chromium soak.**
   - In report 2's B10, one frame took 632,481.8 ms, about 10.5 minutes. This was a SwiftShader
     GPU-process stall in `gl.finish()`.
   - It stretched the 30-minute logical soak to about 46 minutes of wall time.
   - The runner's watchdog (soak + 7 × 65 s + 10 min = 2,855 s) fired at 10:49:51Z, just before
     the B10 cell arrived. The cell is in the report, which carries
     `runError: "timeout after 2855000 ms"` and exited 1.
   - After the stall, the paced loop ran events back to back until it caught up.
4. **The Chromium arm loads the host itself.** The SwiftShader GPU process uses about 5.3 of the 8
   logical CPUs for the whole arm: at 10:07:36Z it used 105 CPU-s per 20 s, against 0.98 for the
   renderer. This arm is a software-GL baseline, not the real GPU (README).
5. **Spikes from other sessions.** Short `git` and `chrome-headless-shell` jobs from other sessions
   pushed the CPU to 100 % at times; those spikes are the gate waits in the runs table. The WMI
   `Win32_Processor` query also failed now and then while the SwiftShader arm ran, and each failure
   counted as "not quiet".
6. **CSP notices.** The hardened Electron shell logged three CSP `style-src 'self'` notices for
   the inline styles in `page/matrix.html`. They are cosmetic, and the README documents them.

## Not run or not measured

- **The Tauri / WebView2 arm.** The ruling dropped it, so ADR-0011 criteria 1-4 are not measured
  and are decided on criterion 5. The evidence is E10-K01 (`docs/plan/spikes/E10-K01.md`), and
  E06-T03 (#222) records the amendment. That is why criteria 1-4 read NO-DATA in
  `adr-0011-table.md` and why its verdict line reads "INCOMPLETE (no-data in >=1 criterion)".
- **The co-tenancy variant of B5 (dev stack up) and the shell memory comparison.** The dev stack
  (WSL, Docker, QuestDB, Postgres) was not running on this host and was not started, because it is
  outside the ruling's scope. Electron's memory is recorded above, but there is no second shell to
  compare it with.
- **Secondary gates the matrix harness does not measure:** the B2 LOD-change count, B3 text
  batching and text draw calls, B4 upload bytes/s and texture memory, B7 frame time, and B9
  SDF-atlas time.
- **B6 and B8** are not in the ticket's matrix scenario set.

## Files

| File                                     | sha256                                                             |
| ---------------------------------------- | ------------------------------------------------------------------ |
| `electron-2026-10-29T08-59-53-274Z.json` | `7d43a2434aeda140f5b22ef0818ba24dcd243e0c26221ce9bbd5bd6b5a9199d8` |
| `chromium-2026-10-29T10-02-17-231Z.json` | `14c9780df733c5e5df4a132689cb986956fd06202f22c513d058efa74164eb11` |
| `electron-2026-10-29T10-55-25-308Z.json` | `ab745f7ccff653e119d46b16ec8b8df53558aea154e94c5f78cf9c28474486ea` |
| `electron-2026-10-29T10-57-08-614Z.json` | `c624b97f9a2a2ca7c54ec5db31fd677de6d7a80e9099f48faedf539cfc42ebb4` |
| `chromium-2026-10-29T10-59-08-627Z.json` | `d9c81b097570537d659a042c551c068ba282365bb5110abb278f833a2c3017b1` |
| `adr-0011-table.md`                      | `629f65d904e538d04eee3090a2bc907426a889b1176eef1f9c540429b5c8053f` |

Each report embeds its version manifest (`manifest`, schema `cv-version-manifest/1`). It records
the CPU, GPU, driver, OS build, the Electron, Chromium and Node versions, and the flag set.
`manifestIncomplete` is empty in all five reports. The reports and the table are excluded from
prettier (`.prettierignore`), so they stay byte-identical to what the harness wrote.

To reproduce, start from `packages/chart-engine` with the README prerequisites in place. Run
`node bench/matrix/run-matrix.mjs --runtime electron --flagset tuned` and
`node bench/matrix/run-matrix.mjs --runtime chromium`. Reports 3-5 add the `--flagset` and
`--scenarios` values from the runs table. The table comes from
`node bench/matrix/compare-matrix.mjs <report 1> <report 2> --out adr-0011-table.md`.
