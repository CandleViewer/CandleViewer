# ADR-0011 — Electron vs Tauri for the desktop shell

- Status: **decided** — 2026-10-29: Electron (see "Decision — 2026-10-29"). Was **proposed** (decision deadline: end of Sprint 03, gated on spike S1 / engine milestone M0)
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

## Decision — 2026-10-29

Recorded by E06-T03 (#222). The proposal-time text above is kept as written; this section is the decision.
Evidence: the M0 findings report `docs/plan/spikes/E06-M0-report.md` (E06-T02; §4 is its ADR-0011 table)
and the criterion-5 evidence in `docs/plan/spikes/E10-K01.md` §4. The report's generated tables are the only
source of matrix figures: this section cites their sections and rows and repeats none of them.

- **Deciders:** Architect, Chart-engine lead, Frontend lead, Owner — recorded under the orchestrator's
  delegation (#220, 2026-10-29 08:40Z); Architect / Security-engineer sign-off comments pending on #222.
- **Outcome: Electron is confirmed as the desktop shell. Tauri v2 is rejected-with-evidence on criterion 5.**
  The rule above applies as written: "if any criterion fails, Electron is confirmed".
- **How it was decided:** the ruling of #220 (2026-10-29 08:40Z) dropped the Tauri / WebView2 measurement arm
  because criterion 5 already fails for Tauri on E10-K01's evidence and `apps/desktop` ships the hardened
  Electron shell every downstream epic builds on. Criteria 1–4 were therefore not measured for WebView2. No
  Tauri figure exists, and none is implied below.

### The five criteria

Criteria 1–4 compare WebView2 with Electron. With no WebView2 arm, each reads "not measured — decided on
criterion 5". The Electron-only rows the report has are cited as **context for Electron, not as a comparison**
(report §4).

| #   | Criterion (as bound above)                                                                           | Status                                             | Electron context (report rows; no comparison)                                                                                           |
| --- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | B5 p95 in WebView2 within 10 % of Electron                                                           | Not measured — decided on criterion 5              | Electron B5 met its p95 gate: report §3.2, row "Electron"; its A/B/A repeat stayed inside this criterion's 10 % band (report §3.6)      |
| 2   | No B10 outliers above 33 ms that are absent under Electron                                           | Not measured — decided on criterion 5              | Electron's B10 outlier count and largest frame: report §3.5, row "Electron", column "Frames > 33 ms"                                    |
| 3   | No progressive `texSubImage2D` degradation over 30 minutes                                           | Not measured — decided on criterion 5              | Electron's per-minute upload median stays under the harness timer's resolution through the soak (report §3.4, §3.5; `SUMMARY.md` "B10") |
| 4   | WebGL2 capability parity (`EXT_color_buffer_float`, R16F, instancing, `OffscreenCanvas` in a worker) | Not measured for WebView2 — decided on criterion 5 | Electron has full parity, WebGL2 in a worker included: report §5, capability row "electron"                                             |
| 5   | A documented, working equivalent of every shell responsibility                                       | **Fails for Tauri**; satisfiable for Electron      | Item by item below                                                                                                                      |

The proposal's "100–150 MB higher resident memory" estimate has no second shell to compare with. Electron's
own memory figures are report §3.5 and are inconclusive on the below-class host (report §2 V5); they are not
evidence for or against this decision.

### Criterion 5, item by item

Criterion 5 is a checklist, not a measurement (`34-e06-shell-threat-model.md` §4 turns it into pass/fail
items; E10-K01 §1 maps every responsibility to a `ShellPort` surface). "Satisfiable" means the shell provides
a working mechanism for the responsibility; where production wiring is still open, the owning ticket is named.

| Responsibility                            | Electron                                    | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ----------------------------------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OS-keychain bridge for the KEK (ADR-0009) | **Satisfiable** — by the host launcher      | ADR-0009 keeps the KEK in the Windows Credential Manager, injected into the backend by the host launcher; the shell carries only an opaque per-session handle over one allow-listed channel and never key material (`04` SR-119): `apps/desktop/src/main/keychain.ts`, `src/preload/allowList.ts`, `test/keychain.test.ts`; E10-K01 §1 row "OS-keychain bridge". `34` §4 item 6 (store/retrieve round-trip) is met by ADR-0009's host launcher, not by the shell, which SR-119 forbids from touching key material; the shell's handle is a placeholder until the backend consumes it. Security-engineer confirmation (STRIDE I / E, `04` §5.9, §6.11) pending on #222 |
| Auto-update with signature verification   | **Satisfiable** — deliberately disabled     | Electron's updater supports signature-verified updates (E10-K01 §4, row "Auto-update"); `apps/desktop/src/main/updateChannel.ts` keeps it off with no install path until code signing is operational (`04` SR-115); E43-T02 (#1231) records that decision and the SR-118 integrity check                                                                                                                                                                                                                                                                                                                                                                              |
| Deep links                                | **Satisfiable** — route validation working  | `ShellPort.deepLinks` (E10-K01 §1); route-level deep-link validation shipped with E10-T01 (#235, `apps/web/src/routes/params.ts`); the main-process protocol handler, navigation intents only (`04` SR-117), is E43-T02 (#1231)                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| Multi-window workspace persistence        | **Satisfiable** — port and adapter in place | `ShellPort.windows.saveState/restoreState` and `apps/web/src/shell/ElectronShellAdapter.ts` (E10-K01 §1); the main-process handlers and per-workspace floating windows are E15-S02 (#435); persisted state carries no secret (`34` §4 item 10)                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Playwright-drivable E2E                   | **Satisfied** — working in CI               | `apps/desktop/e2e/` drives the shell through Playwright's Electron driver, including `hardening.spec.ts`, which reads live `webPreferences`; the nightly Electron matrix runs under `xvfb-run` (report §12); the full shell suite is E10-Q02 (#301)                                                                                                                                                                                                                                                                                                                                                                                                                   |

E10-K01 §1 maps four more responsibilities outside the criterion's five: tray, OS notifications, crash log,
and GPU info and flags. Electron has a native mechanism for each; the crash log and GPU info and flags are wired
today (`apps/desktop/src/main/crashLog.ts`, `gpu.ts`, `apps/desktop/GPU_FLAGS.md`), and the shipped `tuned`
GPU flag set stands (report §3.6: no measurement gives a reason to change it).

### Tauri: rejected-with-evidence

- **Failed criterion: 5.** Two of the eight shell responsibilities in E10-K01 would need real redesign under
  Tauri v2 (E10-K01 §4): **GPU flag control** (Tauri has no bundled-Chromium GPU flag surface and reads
  whatever the OS WebView reports) and **Playwright-driver maturity** (`tauri-driver` exists but is less mature
  than Playwright's Electron driver, and would need its own E2E harness). The other six are close to direct
  ports (same section).
- **Not measured:** criteria 1–4. This decision makes no claim about WebView2 frame times, outliers, upload
  behaviour or capability parity.
- **Shelf life of the rejection:** WebView2 is OS-updated, so any future WebView2 figure would be valid only
  for its recorded runtime version; none was recorded (report §5, "Shelf life").
- **No further Tauri spike** is scheduled without a new, stated question. `34` §7's Tauri-conditional
  constraint (an `invoke()` allow-list, E2) and `34` §8's conditional register entry lapse with this decision.

### Electron hardening: binding on E10

The proposal's hardening list moves from "Negative / risks" to binding requirements on every Electron build
E10 ships; each item is a `04-security-program.md` §6.11 requirement and a checklist item there, not a default.
Relaxing any one is a defect against this ADR, not a configuration choice.

| Item                                 | Requirement         | Where it is enforced today                                                                                                                                                                                          |
| ------------------------------------ | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `contextIsolation: true`             | SR-110              | `apps/desktop/e2e/hardening.spec.ts` and the `electron-hardening` gate                                                                                                                                              |
| `nodeIntegration: false`             | SR-110              | Same                                                                                                                                                                                                                |
| `sandbox: true`                      | SR-110              | Same                                                                                                                                                                                                                |
| Strict CSP, no `unsafe-eval`         | SR-112              | `apps/desktop/src/main/csp.ts` on every `app://` response; `style-src 'unsafe-inline'` is the one SR-112-permitted exception, pending nonce-based styles; directive set and its retirement owned by E43-T01 (#1230) |
| Allow-list preload, no generic IPC   | SR-111              | `apps/desktop/src/preload/allowList.ts`; IPC answered only for the app origin's main frame                                                                                                                          |
| Navigation and `window.open` blocked | SR-113              | `will-navigate` / `will-redirect` restricted to the app origin, `setWindowOpenHandler` denies (`apps/desktop/README.md`)                                                                                            |
| Signed auto-updates                  | SR-115 (and SR-118) | Updater disabled until signing is operational; E43-T02 (#1231) gates it on the packaged artefact                                                                                                                    |

### Chromium security-update treadmill

- **Owner: the Frontend lead**, accountable for "Electron shell & packaging" in `33-raci.md`, with the Security
  engineer and DevSecOps responsible on that row (`34` §7 E4 asked for a named owner).
- **Recurring chore:** track each Electron stable release that carries Chromium security fixes and ship it
  within C-12.3's patch window for the advisory's severity;
  every bump re-runs the `electron-hardening` gate and the nightly Electron matrix (report §12), because the
  M0 figures are bound to the recorded versions. Not filed under the filing freeze: it is a follow-up below.

### Shelf life

The Electron figures belong to the versions in the report's §5 manifest (Electron 45 / Chromium 156, the
recorded GPU driver, Node). A Chromium or driver bump can move them; the CI job keeps measuring, recording
only (report §5 "Shelf life", §12). Nobody should cite them later as durable properties of Electron.

### Desktop screen-reader scope

With Electron decided, the desktop surface's screen-reader stack is `05-accessibility-standard.md` §8.1's
Electron rows: on **Windows 11, NVDA** against the Electron production build (row 1, P0 release blocker) and
**JAWS** (row 2, full pass before R4); on macOS, VoiceOver against the Electron build (row 4, before GA).
Headless Chromium with NVDA (row 3) is fast CI feedback only, not a production target. The E2E accessibility
tests run against the Electron build.

### Follow-ups

Filing freeze: no new issues. After merge, the lane comments on each existing ticket below, citing this
section.

| Ticket                                   | Inherits                                                                                                         |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| E10 (#37) epic                           | The decided shell; its "ADR-0011 is the only non-decided ADR" premise is now closed                              |
| E10-Q02 (#301) Playwright-Electron suite | The hardening list as runtime assertions; the `tuned` GPU flag set; Electron under `xvfb-run` in CI (report §13) |
| E10-Q03 (#302) shell accessibility audit | The desktop screen-reader scope above (NVDA and JAWS on the Windows Electron build)                              |
| E10-Q04 (#303) shell cold start          | B9 is not a process cold start (report §3.1 note, §13); the shelf-life note                                      |
| E10-S04 (#306) system-state surfaces     | The GPU flag set and the GPU-crash path on the decided shell (`apps/desktop/GPU_FLAGS.md`)                       |

Outside E10, the packaged-artefact hardening items are E43-T01 (#1230) and E43-T02 (#1231), multi-window
persistence is E15-S02 (#435), and the JAWS full pass is E47-Q02 (#1355); they get the same comment. The
closed E10 hardening tickets (E10-T02 #236, E10-X02 #307) get none (report §13). **Unfiled:** the recurring
Chromium security-update chore above, for the orchestrator to file when the freeze lifts.
