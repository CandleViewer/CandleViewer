# ADR-0011 — Electron vs Tauri for the desktop shell

- Status: **proposed** (decision deadline: end of Sprint 03, gated on spike S1 / engine milestone M0)
- Date: 2026-09-14
- Deciders: Architect, Chart-engine lead, Frontend lead, Owner
- Consulted: `docs/research/10-frontend-tech.md` (Tauri/Electron section, finding #29), `docs/research/24-owner-decisions.md` decision #7
- Related: ADR-0002, `docs/plan/26-chart-engine-design.md` §14 (M0)

## Context and problem statement

The web app needs a desktop wrapper for window management, workspace persistence, the OS-keychain bridge for the KEK, deep links and auto-update. The research report initially recommended Tauri for its memory footprint (relevant when running alongside a Python backend and WSL on the same machine). The owner then prioritised **performance and smoothness**, noting that with a fully custom WebGL engine, predictable GPU behaviour matters more than resident memory. Tauri's WebView2 behaviour under sustained 100 ms heatmap texture updates is unverified, and it varies by OS-provided WebView version — precisely the variability a custom engine cannot absorb.

## Decision drivers

- Custom WebGL2 engine with hard frame budgets (`26-chart-engine-design.md` §13) and a 100 ms heatmap update cadence.
- Electron bundles a known Chromium build with controllable GPU flags; WebView2 is an OS-updated component whose behaviour can change under the application.
- Memory footprint matters because the same machine runs WSL, Docker, QuestDB and Postgres.
- The web app is shell-independent by construction, so this decision is genuinely reversible — which is why it can stay open without blocking work.

## Considered options

1. **Electron** — bundled Chromium, pinned version, explicit GPU flags.
2. **Tauri v2** — OS WebView (WebView2 on Windows, WKWebView on macOS, WebKitGTK on Linux), Rust host.
3. **Browser only, no desktop shell.**

## Decision outcome (interim)

**Interim: Electron is the default and is what the team builds against**, per owner decision #7. The Tauri comparison is measured in spike S1 / milestone M0, which runs benchmarks B3 (footprint text) and B4/B5 (heatmap) in Chromium, Electron **and** Tauri/WebView2 on the reference machine.

### Decision criteria (binding, applied at the deadline)

Tauri is adopted **only if all** of the following hold in the M0 report:

1. p95 frame time for B5 in WebView2 is within **10 %** of Electron on the same machine.
2. No frame-time outliers above 33 ms during a 30-minute heatmap soak (B10) that are absent under Electron.
3. `texSubImage2D` streaming at 10 Hz shows no progressive degradation over 30 minutes.
4. WebGL2 capability parity: `EXT_color_buffer_float`, `R16F` render/sample support, instancing, and `OffscreenCanvas` in a worker all available.
5. A documented, working equivalent of every shell responsibility: OS-keychain bridge for the KEK, auto-update with signature verification, deep links, multi-window workspace persistence, and Playwright-drivable E2E.

If any criterion fails, **Electron is confirmed** and this ADR moves to `decided` with Tauri recorded as rejected-with-evidence.

### Interim consequences

Positive:

- Chromium is pinned, so GPU behaviour is reproducible across machines and across time — the property the chart engine's benchmarks depend on.
- Mature tooling: `electron-builder`, code signing, Playwright's Electron driver, crash reporting.
- The engine's `RenderProfile` probe and `degraded-2d` fallback already handle capability variance, so a later switch is not a cliff.

Negative / risks:

- Resident memory is roughly 100–150 MB higher than Tauri, on a machine already running the full backend stack. Accepted; measured in M0 and reported.
- Electron's security posture requires deliberate hardening: `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, strict CSP, an allow-list preload, navigation and `window.open` blocked, and signed auto-updates. These are mandatory checklist items in `04-security-program.md`, not defaults.
- Larger installers and a Chromium update treadmill (security patches must be tracked and shipped).

### Why not the alternatives

- **Tauri today**: the unverified WebView2 behaviour under our specific, unusual workload is exactly the risk the owner chose not to take while also choosing a fully custom renderer. It stays a live candidate precisely because the app is shell-independent.
- **Browser only**: loses the OS-keychain bridge (central to ADR-0009), workspace persistence, GPU flag control and deep links. The browser remains a fully supported deployment target for managers, but it is not the owner's primary surface.

## Validation

- M0 benchmark report covering all five criteria above, published in `docs/plan/` and linked from this ADR.
- M0 findings report (E06-T02): `docs/plan/spikes/E06-M0-report.md` — criteria 1–5 in §4, the Electron runs in §3.
- Whichever shell wins runs the full E2E suite in CI on every release.

### E10-K01 addendum — criterion-5 evidence (ShellPort spike, 2026-09-29)

`docs/plan/spikes/E10-K01.md` records the shell-responsibility (criterion 5) column that M0 (E06-K01/K02,
merged) did not address: a typed `ShellPort` interface (`apps/web/src/shell/ShellPort.ts`) covering every
responsibility in criterion 5, an `ElectronShellAdapter` proving the preload bridge needs no generic IPC
escape hatch (SR-111), and a `BrowserShellAdapter` proving honest capability degradation (US-SET-009). Of
the eight responsibilities, six (window persistence, keychain, auto-update, deep links, tray, OS
notifications) have a close-to-direct Tauri v2 equivalent; two (GPU flag control, Playwright-driver
maturity) would need real redesign under Tauri. This is evidence only — it does not decide criteria 1–4
(frame-time parity), which remain gated on the M0 report content. The interim decision (Electron is the
default) is unchanged.
