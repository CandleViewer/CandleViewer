# E06-T01 matrix: ADR-0011 criteria

Runtimes: electron, chromium | Comparable: yes

| # | Criterion | Figure | Result |
|---|---|---|---|
| 1 | B5 p95 WebView2 within 10 % of Electron | Electron 0.50 ms vs WebView2 n/a ms = n/a % (threshold 10 %); WebView2 VERSION MISSING — B5 p95 missing in one arm | **NO-DATA** |
| 2 | No >33 ms soak outliers absent under Electron (B10) | outliers >33 ms: Electron 2, WebView2 n/a — B10 missing in one arm | **NO-DATA** |
| 3 | texSubImage2D 10 Hz: no progressive degradation (B10) | n/a — needs a >= 3 minute B10 soak with upload samples | **NO-DATA** |
| 4 | WebGL2 capability parity (EXT_color_buffer_float, R16F, instancing, OffscreenCanvas in worker) | all present — no capability probe in the Tauri report | **NO-DATA** |
| 5 | Shell responsibility parity |  — checklist from E06-X01 / E10-K01 (docs/plan/spikes/E10-K01.md): cannot be computed from frame data | **MANUAL** |

**R0 exit criterion 4 (Electron B5):** PASS — p50 0.20 ms (5000.0 fps), p95 0.50 ms (2000.0 fps), 15 draw calls; B5 gates p95<=16.7: true, draws<=40: true

**Verdict:** INCOMPLETE (no-data in >=1 criterion)

- electron: Intel(R) Core(TM) i7-8550U CPU @ 1.80GHz / Intel(R) UHD Graphics 620 (31.0.101.2135) / win32 10.0.26300 / Electron 45.0.0 Chromium 156.0.8078.48 Tauri - WebView2 - Node 20.19.5; flags: electron-tuned; seed 20260928; fixture sha256 dedf0e86781c31341d6e54e992ad0cfe85c2b65e25011becaff131eb77a9e579
- chromium: Intel(R) Core(TM) i7-8550U CPU @ 1.80GHz / Intel(R) UHD Graphics 620 (31.0.101.2135) / win32 10.0.26300 / Electron - Chromium 156.0.8078.4 Tauri - WebView2 - Node 20.19.5; flags: pinned-K01 (software GL; override with a real-GPU set on the reference machine, see README); seed 20260928; fixture sha256 dedf0e86781c31341d6e54e992ad0cfe85c2b65e25011becaff131eb77a9e579
