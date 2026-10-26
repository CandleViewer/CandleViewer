# E06-T01 measurement matrix: owner runbook

Prep only. Nothing here has been run on the reference machine. The measurement is owner item **T** on #1778. This
directory is the driver, the harness shells and the comparison tool, so the run takes about an hour of attended time.

## What was and was not verified before handing this over

| Piece                                                                       | State                                                                                                                                                                                                                           |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run-matrix.mjs --runtime chromium` (headless, real WebGL2 via SwiftShader) | Ran end to end (B1,B5), report valid, manifest complete                                                                                                                                                                         |
| `--dry-run` (B5 composition, B7 logic, manifest)                            | Ran, passes                                                                                                                                                                                                                     |
| `compare-matrix.mjs` criterion 1 at the 10 % boundary, both sides           | Unit-tested (`test/bench/matrix/`)                                                                                                                                                                                              |
| Electron shell (`electron/`)                                                | **Launched on Windows 11, 2026-10-26** (Electron 45.0.0 / Chromium 156, ANGLE D3D11; B1 / B5 / B10 smoke, 1 rep, 5k bars). Non-reference host, so not evidence                                                                  |
| Tauri shell (`tauri/`)                                                      | **Written, not compiled**: no Rust toolchain was available offline. Crate versions in `Cargo.toml` are exact pins I could not resolve offline: if `cargo` rejects them, bump to the nearest Tauri 2.x and note it in the report |

## Prerequisites (reference machine)

1. Windows 11, the reference GPU with current driver, power plan "High performance", plugged in.
2. Close everything else. **Exception:** the co-tenancy run (below) wants the dev stack (WSL, Docker, QuestDB, Postgres) up.
3. **Node ≥ 20.19** (the repo's `engines` floor; `.nvmrc` pins 20.19.5). `electron@45`'s installer needs
   `require(esm)`: on Node 20.14 the Electron arm dies before launch with `ERR_REQUIRE_ESM`.
4. `pnpm install --frozen-lockfile` at the repo root. Electron and Playwright come from `apps/desktop`.
5. Then `node tools/ci/run-allowed-postinstall.mjs` (the SR-138 allowlist runner; about 150 s). It fetches the
   Electron binary, because Electron ≥ 42 has no postinstall of its own. Without it, the first launch fails with
   "Electron failed to install correctly".
6. Chromium arm: `pnpm --filter @candleviewer/desktop exec playwright install chromium` (once).
7. Tauri arm: Rust (stable, MSVC) + the WebView2 runtime (Evergreen, preinstalled on Win 11). Then:
   `cd packages/chart-engine/bench/matrix/tauri/src-tauri && cargo generate-lockfile && cargo audit`
   (commit the lockfile with the results; supply-chain rules are E06-X02).
8. Note the background load (Task Manager) in the issue comment.

## The three commands (same seed and fixture on all three)

Run from `packages/chart-engine`. Defaults are the real thing: 3 reps, 100k-bar M0 fixture, seed `20260928`,
20 s per repetition, 30 min B10 soak (once per runtime).

```bash
node bench/matrix/run-matrix.mjs --runtime electron --flagset tuned
node bench/matrix/run-matrix.mjs --runtime tauri
node bench/matrix/run-matrix.mjs --runtime chromium     # baseline smoke arm (scope trim)
```

Ticket asks for A/B/A ordering to cancel thermal drift. Do the whole sequence **electron, tauri, electron** (the
second Electron report is also your same-scenario noise-band check: B5 medians of p95 must agree, see below), and
chromium last. Also run, once each:

```bash
node bench/matrix/run-matrix.mjs --runtime electron --flagset default    # flag-set A/B -> E10 recommendation
node bench/matrix/run-matrix.mjs --runtime electron --flagset tuned --cotenancy --scenarios B5   # dev stack UP
node bench/matrix/run-matrix.mjs --runtime tauri --cotenancy --scenarios B5                       # dev stack UP
```

**Expected duration:** each full run is about 3 min of fixture generation and setup + 8 scenarios x 3 reps x ~20 s +
the 30 min soak, so about 40 min per runtime. The full sequence is therefore well over an hour of wall time. To fit
one hour, run the soak only in the first Electron and the Tauri run: pass `--scenarios B1,B2,B3,B4,B5,B7,B9` on the
repeat Electron run and the flag-set/co-tenancy variants. Run unattended, do not touch the machine.

## Compare

```bash
node bench/matrix/compare-matrix.mjs reports/matrix/electron-<ts>.json reports/matrix/tauri-<ts>.json \
     reports/matrix/chromium-<ts>.json --out reports/matrix/adr-0011-table.md
```

Exit code 1 means at least one criterion failed. The table has the measured figure and pass/fail for criteria 1-4,
the R0 exit-criterion-4 verdict on Electron's B5 (p50 <= 16.67 ms and p95 <= 18.18 ms, plus the B5 gates), and warns
if the runs are not like-for-like (different fixture hash, seed, driver hash or machine).

Criterion 5 is a checklist (E06-X01, `docs/plan/spikes/E10-K01.md`), not a number: it prints as `MANUAL`.
Criterion 3's "no progressive degradation" has no number in ADR-0011. The tool compares the last third with the
first third of the soak's per-minute `texSubImage2D` medians and uses **10 %** (our assumption, printed in the
table, change with `--degradation-tolerance`). Confirm or replace it at Architect review.

## Where reports land and what to paste into #220

`reports/matrix/<runtime>-<timestamp>.json` (repo root). Each carries seed, fixture sha256, driver-script hash, the full
version manifest (CPU, GPU, driver, OS build, Electron, Chromium, Tauri, WebView2, Node, flag set), WebGL2
capability probe, per-cell medians of p95, B10 per-minute soak buckets, and resident memory. A run with an
incomplete manifest exits 1 and lists the missing fields (e.g. a Tauri report without a WebView2 version is
rejected).

Paste into #220: (1) the `adr-0011-table.md` output; (2) the one-line manifest per runtime (printed at the bottom
of the table); (3) resident-memory peak per shell (`residentMemoryMb.peakMb`) for the ADR's "100-150 MB" claim,
the co-tenancy B5 figures, and which Electron flag set won (for E10); (4) the noise-band check: the two Electron
runs' B5 `p95` agree within the band, otherwise the matrix is **not admissible**. Raw JSON files are committed with
the report PR (E06-T02), not here.

## How the numbers are produced

- One page (`page/matrix.html` + `page/page-main.mjs`) is served by a loopback server and loaded by all three
  shells, so the driver script is identical. The runner hashes it into each report.
- The K02-K04 scene classes model their GPU cost (they predate any GL context). To stop every runtime looking
  identical, `page/gl-load.mjs` adds **real** WebGL2 work each frame (2,500-instance draws x the scene's draw count,
  `gl.finish()`, a column `texSubImage2D` on every heatmap event) and a 100-node DOM-mirror update (E06-D03 stage).
  Frame time is `scene.step + GL + DOM` wall-clock. The scenes' modelled per-stage costs are recorded separately
  (`modelledStageMs`) and are not part of the headline p95.
- B7 runs both `worker` (OffscreenCanvas in a Worker) and `inline` (`RunMode.inline`); the two are reported
  separately and never averaged. A runtime without OffscreenCanvas-in-worker records the gap (criterion 4) and
  still gets the inline result.
- B10 adds the 10 Hz heatmap stream to the driver's pan-only soak script, because criteria 2 and 3 are about that
  stream.
- The Chromium arm uses the K01 pinned flags (`PINNED_CHROMIUM_FLAGS`, SwiftShader software GL), so on the
  reference machine it is **not** the real GPU. It is only the shell-vs-engine attribution baseline. The Electron
  and Tauri arms use the real GPU.

## Flag sets

`electron/flagsets.cjs`: `default` (no extra switches) and `tuned` (exactly `apps/desktop/src/main/gpu.ts`, rationale
in `apps/desktop/GPU_FLAGS.md`: `--enable-gpu-rasterization`, `--disable-features=CalculateNativeWinOcclusion`).
No flag was invented. The winner goes to E10; if a new flag is wanted, add its justified row to `GPU_FLAGS.md` first.
Tauri/WebView2 gets none (WebView2 owns its flags).

## Hardening carried by the Electron shell (E06-X01)

`contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, `webSecurity`, strict CSP header, allow-list
preload (read-only marker, no IPC), `window.open` denied, cross-origin navigation blocked, all permission requests
denied, loopback URL only. The Tauri shell registers no commands/plugins and has an empty capability set.

## Known limitations

- The harness page is a spike-only prototype (not production engine code).
- The Tauri host is unbuilt (see top table). The Playwright-for-Tauri arm is not provided: Tauri is launched by
  `cargo run` and reports through the same HTTP sink.
- Resident memory uses the OS working set (summed by process name) and, for Electron, `app.getAppMetrics()`.
- B9 is measured as a JS cold-init to first modelled frame + first GL draw, not a process cold start.
- Under the hardened shell the matrix page logs three CSP `style-src 'self'` notices for the inline styles in
  `page/matrix.html`. They are cosmetic and don't affect the canvas measurement.
