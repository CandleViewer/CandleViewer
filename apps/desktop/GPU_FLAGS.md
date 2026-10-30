# Electron GPU command-line flags

Source of truth for every `app.commandLine.appendSwitch(...)` call in
`src/main/index.ts`. Each flag below has a rationale so an undocumented
flag never lands "because it fixed something once" (risk R8 — the classic
source of "works on the reference machine only").

**Status of the underlying measurement (2026-09-29):** the M0 Electron-vs-Tauri
benchmark report (`docs/plan/27-adrs/ADR-0011-electron-vs-tauri.md`) has not
yet published a GPU-flag-tuning result — `docs/plan/spikes/E06-K02.md` records
that no real GPU-backed scene exists yet to measure against (the engine
milestone that first drives one is E06-T01, still open). This ticket therefore
ships the conservative, widely-documented Chromium/Electron flag set below —
each justified by Electron/Chromium's own documented behaviour, not by an
E06 benchmark number — and is designed to be revisited (flags added, changed
or removed) the moment E06-T01 lands a real measurement. Revisiting this file
does not require an ADR; it does require updating the "Justification" column.

| Flag                       | Value                         | Justification                                                                                                                                                                                                                                                                                                                                                     |
| -------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--disable-gpu-sandbox`    | _(not set)_                   | Deliberately **not** applied — the GPU process sandbox stays on; disabling it would trade a defence-in-depth layer for an unmeasured performance gain (STRIDE E1 relevance: keep every sandbox boundary Electron offers).                                                                                                                                         |
| `enable-gpu-rasterization` | _(feature enabled)_           | Chromium's documented default-on path for compositor-driven canvas/WebGL content; keeps GPU raster consistent across the reference Windows host and CI headless Chromium so the chart engine's frame-time budget (`06-performance-and-load-standard.md` budget #1) is measured against the same rasterization path in both places.                                |
| `disable-features`         | `CalculateNativeWinOcclusion` | Windows' native-occlusion tracking can pause compositor work for a window it (incorrectly) believes is fully occluded behind another always-on-top utility window on a multi-monitor trading desk; disabling it avoids a class of "chart froze until I clicked the window" reports that are otherwise very hard to reproduce.                                     |
| `ignore-gpu-blocklist`     | _(not set)_                   | Deliberately **not** applied — silently overriding Chromium's own hardware blocklist would let a genuinely unsupported GPU driver render into the `degraded-2d` fallback path unnecessarily invisibly; if the reference machine ever needs an override, that decision must be visible in this table with the specific GPU/driver it targets, not applied blanket. |

No flag here disables `webSecurity`, changes a CSP-relevant Chromium switch,
or affects `contextIsolation`/`sandbox` — those are `webPreferences`, not
command-line switches, and are asserted independently by SR-110's test suite.

`gpu.info()` (`ShellPort`) exposes the live probe result (vendor, renderer,
hardware-accelerated flag, WebGL2 capability parity) so the renderer can
enter the `degraded-2d` path (`docs/plan/20-architecture.md` F15) when the
probe fails, independent of which flags are set here.
Main's `cv:gpu:info` answer also carries `lastCrash` (#4951): the session's last
GPU-process crash (time, restart count, reason, `retried`, `kept`), or `null` before one.
