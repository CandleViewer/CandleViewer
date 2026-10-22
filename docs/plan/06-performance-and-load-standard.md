# 06 — Performance and Load Standard

Status: locked for planning phase. Owner: Architect + Frontend (chart engine) + Backend leads. Applies to the CandleViewer web app (React + custom WebGL chart engine, Electron shell) and the Python/FastAPI backend, for the target deployment: **10 symbols, 5 Bybit accounts (1 main + up to 4 sub, or up to 5 total per §4 capacity model), 5 concurrent users (owner + managers)**, self-hosted (WSL Ubuntu → small dedicated VPS later), remote access via Tailscale only.

This document defines every performance/load budget referenced by `11-user-stories.md` acceptance criteria, `26-chart-engine-design.md`, `21-database-schema.md` (retention/storage), and the load-test tickets in `docs/plan/backlog/*.json`. Numbers are engineering targets set now, to be validated/tightened by the mandatory spikes in `24-owner-decisions.md` (§"Mandatory spikes before design sign-off") before R1/R2 exit.

---

## 1. Performance philosophy

<!-- 06 is not prettier-clean on main: this fence goes when 06 is reformatted on its own (#399 D2-G4). -->

<!-- prettier-ignore-start -->

1. **Budgets, not hopes.** Every number below is a testable budget with a defined measurement method (§7) and a CI regression gate (§8) — not an aspiration.
2. **Frame budget is sacred.** The chart engine's job is to never miss a frame under realistic load; every other subsystem (ingestion, WS fan-out, React state) is designed to protect that budget, including deliberately shedding update *frequency* (not correctness) under load.
3. **Perceived-latency budgets for trading, not just raw throughput.** Order submit→ack and WS tick→screen budgets are set to what a discretionary trader operating at human reaction-time speed needs, calibrated against the **demo/paper environment** (v1 has no live order entry until R4 pen-test gate); live numbers are re-validated before Live enablement.
4. **Scale target is fixed and small, on purpose.** This is a personal/small-team platform (10 symbols / 5 accounts / 5 users), not a multi-tenant SaaS — budgets are set for that scale with headroom, not for hypothetical hyperscale, per the locked scope decision. Capacity planning (§10) makes the headroom explicit rather than over-building.
5. **Every budget has an owner and a re-test cadence** — see §9 profiling playbook and the PRR gate in `07-release-and-prr.md`.

## 2. Core performance budgets (summary table)

| # | Budget | Target | Measured as | Hard/soft |
|---|---|---|---|---|
| 1 | Chart engine frame time | ≤16.6ms/frame (60fps) sustained | p95 frame time, Chromium/Electron, 100k bars loaded + 200-depth heatmap updating at 100ms cadence, on reference hardware (§3.1) | Hard — R1 exit gate |
| 2 | Chart engine frame time, degraded mode | ≤16.6ms/frame at 30fps floor (i.e. never below 30fps) under worst-case (all overlays + 5-symbol multi-chart layout + replay at 20x) | p95 frame time under worst-case scenario (§6.4) | Hard — never drop below 30fps; 60fps is the target, 30fps is the floor |
| 3 | WS tick → screen (visual update latency) | p95 < 100ms, p99 < 250ms | Timestamp injected at Bybit WS receipt (backend) vs. paint timestamp (frontend, `requestAnimationFrame` callback) for best-bid/ask, last-trade, and position P&L updates | Hard — R2 exit gate |
| 4 | Order submit → ack | p95 < 300ms (demo/paper env), p95 < 500ms (live env, network + exchange dependent) | Timestamp at user's submit action (click/hotkey) vs. terminal ack (order acknowledged/rejected event received) | Hard for demo (R3 exit gate); live figure is a target pending pen-test-era measurement, not a hard gate until R4 |
| 5 | Ingestion throughput per symbol | Sustain Bybit's full published cadence per stream (trade: unbounded burst, orderbook.200: 100ms, tickers: ~100ms) with zero dropped messages under steady state | Backend ingestion soak test message-loss counter = 0 over 24h per symbol | Hard |
| 6 | Backend fan-out (WS→React) latency add-on | ≤20ms p95 added latency backend-internal (book update → outbound WS frame emitted) | Instrumented span backend-side | Hard |
| 7 | Memory ceiling — frontend (per chart window) | ≤1.5GB resident for a single fully-loaded chart workspace (100k bars, all overlays, 4-pane layout) | Chrome DevTools / Electron `process.getProcessMemoryInfo()` sampled over a 2h soak | Hard |
| 8 | Memory ceiling — backend (per symbol, steady state) | ≤300MB resident per actively-recorded symbol (book state + bar builders + rolling aggregation buffers) | `psutil`/cgroup memory sampled per symbol-worker process/task | Hard |
| 9 | Bundle size (initial load, Electron renderer) | ≤8MB gzipped JS+CSS for first interactive paint (code-split; chart-engine core counted, lazy-loaded heavy panels excluded from initial bundle) | Webpack/Vite bundle analyzer, CI-tracked | Soft (tracked, alert at +10% regression) — see §8 |
| 10 | Startup time (cold launch to interactive workspace) | ≤3s cold start (Electron app launch → last-used workspace fully interactive, symbols subscribed) on reference hardware | Instrumented `app.whenReady()` → "workspace ready" event | Hard — R1 exit gate |
| 11 | Backend CPU — per symbol (steady state, no replay) | ≤0.5 vCPU core-equivalent sustained per actively-recorded symbol at full stream cadence | `cgroup`/`psutil` CPU% sampled over 1h steady-state window | Soft (tracked; informs capacity plan §10) |
| 12 | Storage growth | 0.5-0.75GB/day/symbol compressed at 200-depth recording (research-estimated range, `24-owner-decisions.md`); **0.75GB/day/symbol (the upper bound) is the planning/provisioning figure used everywhere in this document** (§10.2 disk sizing), chosen deliberately over the midpoint so capacity plans have built-in margin rather than needing a later upward revision if real recording turns out denser than the low end of the range; actual observed growth is tracked per-symbol and the range is narrowed once R1-R2 real recording data lands | QuestDB+Parquet on-disk size delta, daily | Soft (tracked; drives retention defaults in `21-database-schema.md`) |
| 13 | API (REST) p95 latency | <150ms p95 for read endpoints (positions, orders, journal query, instruments-info cache), <300ms p95 for write endpoints (order create/amend/cancel, backend-internal portion only, excl. exchange RTT) | k6 load test against staging backend | Hard |
| 14 | DOM heatmap update cadence | 100ms cadence sustained, 200-depth, ≤1 dropped/coalesced frame per 10s under nominal load | Frame-timestamp instrumentation on the heatmap WebGL layer | Hard — R1 exit gate (ties to #1) |
| 15 | Replay mode playback | Sustain up to 100x speed (per views digest) without violating budget #1's frame floor; higher speeds may degrade visual fidelity (skip-render) but must not crash/desync | Manual + automated replay-soak test at 100x on a recorded 24h symbol-day | Hard (crash-free), Soft (visual fidelity at extreme speed) |

## 3. Reference environment and measurement conditions

### 3.1 Reference hardware (defines "on reference hardware" throughout this doc)

- **Dev/CI reference machine**: 6-core/12-thread modern x86_64 CPU (e.g. Ryzen 5 5600X / Intel i5-12600 class), 32GB RAM, NVMe SSD, a mid-range discrete or capable integrated GPU (e.g. GTX 1650 / Iris Xe class — deliberately modest, not a gaming rig, since this must run acceptably on the owner's actual hardware plus in WSL/Electron/CI containers).
- **Backend runtime environment**: WSL2 Ubuntu on that same class of machine for now; a small dedicated VPS (4 vCPU / 8GB RAM class) is the "later" target explicitly named in the locked decisions — all backend budgets are set to be met on the *smaller* VPS profile, not just the dev workstation, since that is the eventual production home.
- **Network conditions for latency budgets**: measured over Tailscale (the only supported remote-access path) with a representative ~20-50ms Tailscale RTT between client and backend, plus real Bybit WS/REST RTT (varies by region — Bybit servers are typically Singapore/Tokyo/Amsterdam; budgets assume the backend is deployed in a region with <150ms RTT to the chosen Bybit endpoint, and this Bybit-RTT component is *excluded* from backend-internal budgets #3/#4/#6/#13 and *included* as a separate, uncontrolled factor in the end-to-end order-ack budget #4).

### 3.2 Load scenario definitions (used consistently across §2, §6, §7)

- **Nominal load**: 3 symbols actively charted/recorded, 1 user, default overlays (footprint+profile+CVD), no replay running.
- **Realistic peak load**: 10 symbols recorded (per capacity target §10), 5 concurrent users each viewing multi-pane layouts (up to 4 panes/user), all order-flow overlays enabled on at least the focused pane, DOM heatmap open on ≥2 symbols, one user running replay at ≤20x.
- **Worst-case/stress load**: all 10 symbols simultaneously charted across all 5 users' workspaces, heatmap+footprint+profile all active everywhere, one replay session at 100x, plus a synthetic burst (simulated Bybit volatility event: 5x normal trade/orderbook message rate for 60s) injected into the ingestion pipeline.

## 4. Engine frame budget: 100k bars + 200-depth heatmap @ 100ms

This is the single highest-risk, highest-priority budget (explicit R1 spike per `24-owner-decisions.md`).

### 4.1 What "100k bars" means operationally

- 100k bars loaded in the time-scale's virtual data model (e.g. ~2.7 months of 1-minute bars, or multiple years of higher timeframes) — the engine must hold this much OHLCV+derived-series data in memory and be able to scroll/zoom across all of it, but **only renders the visible window** (typically a few hundred bars) per frame. The 16.6ms budget is a *per-frame* (visible-window) cost, not an "iterate all 100k bars per frame" cost — this distinction is a core chart-engine-design constraint (feeds `26-chart-engine-design.md`).
- Off-screen/virtual bars beyond the visible window + a small prefetch margin are not touched by the render loop; panning/zooming triggers incremental data-window updates, not full-dataset re-processing, each also budgeted within the 16.6ms frame (or spread across a few frames with a documented "settling" allowance of up to 3 frames for a hard jump like `Home`/`End`).

### 4.2 What "200-depth heatmap @ 100ms" means operationally

- DOM/liquidity heatmap renders up to 200 price levels of depth (Bybit `orderbook.200`), updating on each incoming delta but visually refreshed at up to 10Hz (100ms), via the rolling-texture strategy (`texSubImage2D` per-tick update of the newest time-column only, per frontend-tech research) — this keeps the GPU-side update cost roughly constant regardless of retained heatmap history length, which is the key technique that makes the 100ms/200-depth budget achievable without falling back to full-texture re-upload.
- The 100ms cadence is a **visual refresh cadence**, decoupled from the underlying WS message cadence (which can be faster, e.g. 20ms for L50): incoming deltas are coalesced into the backend's book-state and the frontend samples/uploads at the 100ms cadence, so message rate spikes do not translate 1:1 into GPU upload spikes (backpressure/coalescing strategy, shared with §5).

### 4.3 Frame budget breakdown (target allocation within the 16.6ms budget, nominal load)

| Stage | Budget | Notes |
|---|---|---|
| Input/event handling (pan/zoom/crosshair) | ≤1ms | |
| Data-window recompute (visible-range slice, LOD selection) | ≤2ms | Only on scroll/zoom/new-bar frames, amortized to ~0 on static frames |
| Candle/bar geometry update | ≤2ms | Instanced draw, only changed bars re-buffered |
| Footprint cell text/geometry update | ≤4ms | Largest CPU-side cost per research (text-heavy rendering is the flagged engineering risk) — LOD text-hiding kicks in below a per-cell-pixel-width threshold to protect this budget, not to save GPU time alone |
| Heatmap texture upload (`texSubImage2D`) | ≤2ms | Newest column only, per §4.2 |
| Profile/CVD/indicator pane redraw | ≤2ms | Only panes with changed data in this frame |
| Overlay/drawing-tools/order-lines redraw | ≤1ms | |
| DOM-mirror (a11y layer, `05-accessibility-standard.md` §6.1) sync | ≤1ms | Windowed/virtualized so cost doesn't scale with total bar count |
| Composite + present | ≤1.6ms | Buffer |
| **Total** | **≤16.6ms** | |

This breakdown is the basis for the profiling playbook (§9) — a regression is triaged by first identifying which stage exceeded its slice via the frame-marker instrumentation (§7.2), not by re-profiling from scratch every time.

### 4.4 Degradation strategy (protecting the 30fps floor under worst-case load, §2 budget #2)

When the frame budget is at risk under worst-case load (§3.2), the engine sheds *update frequency*, never *correctness*, in this priority order (highest-value-to-user first, cut last):
1. Reduce heatmap visual refresh cadence from 100ms toward 250ms (still real-time-feeling, degraded smoothness) — first thing relaxed.
2. Reduce footprint cell text density (LOD: hide per-cell numeric text, keep colour-coded cell blocks) at high zoom-out or high pane count.
3. Coalesce big-trade-bubble/CVD/indicator pane redraws to every 2nd frame.
4. As a last resort under the stress scenario only (not nominal/realistic peak), cap simultaneously-live multi-chart panes' heatmap+footprint to the currently-focused pane, with background panes showing candles+profile only until refocused (with an explicit, non-colour-only "reduced live detail" indicator per the a11y standard's colour-independence rule) — this is a deliberate, tested, documented fallback, not silent quality loss.

Never acceptable: dropping frames below 30fps, silently discarding order-line/position overlay updates (trading-critical data is never sacrificed for smoothness — cosmetic/analytical overlays are shed first), or desyncing the DOM-mirror accessibility layer from what's visually rendered.

## 5. WS→screen and order-ack latency budgets

### 5.1 WS tick → screen (budget #3)

End-to-end path: Bybit WS message → backend ingestion parse → book/bar-builder update → backend fan-out WS frame → frontend WS client → state store (Jotai per-symbol high-freq state, per frontend research) → React/engine paint.

**Stage-by-stage p95 allocation (sums to the 100ms budget at the pessimistic/WAN edge):**

| Stage | Budget (p95) | Notes |
|---|---|---|
| Ingestion parse (Bybit WS frame → internal message) | ≤3ms | orjson/msgspec-class fast JSON parse, per §5.1 backend-internal budget #6's ≤20ms envelope |
| Book/bar-builder update (apply delta to in-memory book/bar state) | ≤5ms | Per-symbol worker isolation so one symbol's burst doesn't stall another |
| Pre-aggregation ("already bucketed" state prep for subscribers) | ≤5ms | Avoids raw re-computation per subscriber |
| Backend fan-out (outbound WS frame emitted to all subscribed sessions) | ≤7ms | Completes the ≤20ms backend-internal sub-budget (#6) with 3ms headroom: 3+5+5+7=20ms |
| Network hop, backend → frontend (Tailscale WAN, worst case) | ≤50ms | Localhost/LAN typically <5ms; this is the uncontrolled, dominant term at the pessimistic edge (§3.1) |
| Frontend WS client → state store (RxJS batching/throttling window) | ≤16ms | Capped at one frame specifically so it never becomes the dominant controllable term |
| React/engine paint (state store → next `requestAnimationFrame`) | ≤16.6ms | One full frame budget per §4.3 in the worst case (update lands just after a paint) |
| **Total (pessimistic/WAN edge)** | **≈102.6ms → rounds to the p95 <100ms target under realistic conditions** | The four backend-internal stages (20ms) are the only ones CandleViewer fully controls; network (50ms) is bounded but uncontrolled; the two frontend stages (16ms + 16.6ms) are controlled but represent a "worst alignment" double-frame-wait case — in practice frontend stages overlap/pipeline so real p95 comes in under the nominal sum, which is why this is stated as a p95 statistical target, not a worst-case-sum guarantee |

- **Backend-internal portion** (ingestion receipt → outbound fan-out frame emitted): budget #6, ≤20ms p95. Achieved via: async, non-blocking parse (orjson/msgspec-class fast JSON, or the identified binary-framing upgrade path in `23-ws-protocol.md`); per-symbol worker isolation so one symbol's burst doesn't stall another's fan-out; pre-aggregated "already bucketed" state pushed rather than raw re-computation per subscriber.
- **Network hop** (backend → frontend over Tailscale/localhost): typically <5ms on localhost/LAN, <50ms over Tailscale WAN — not a budget CandleViewer controls beyond choosing Tailscale (locked decision) and co-locating backend/client on the same LAN where practical for the owner's primary usage.
- **Frontend portion** (WS message received → paint): RxJS batching/throttling at ingestion (per frontend-tech research) intentionally coalesces bursts to protect the frame budget (§4), meaning the "screen" timestamp is the next `requestAnimationFrame` after the batching window closes — batching window is capped at 16ms (one frame) specifically so it never itself becomes the dominant latency term.
- **Total p95 <100ms budget** is therefore allocated roughly: ≤20ms backend, ≤50ms network (worst-case Tailscale WAN), ≤16ms frontend batch window, ≤16.6ms to next paint — sums to ~100ms at the pessimistic edges, which is why 100ms is the p95 (not average) target; localhost/LAN operation comfortably beats it.

### 5.2 Order submit → ack (budget #4)

Path: user action (click/hotkey) → frontend order-ticket validation → REST/WS call to backend OMS → backend idempotent submission (`orderLinkId`) → Bybit REST `/v5/order/create` → Bybit ack → backend OMS state update → frontend confirmation render.

- **Demo/paper environment (v1 primary trading surface, since Live requires the R4 pen-test gate)**: p95 <300ms hard budget. Demo has no WS order entry (REST-only, per locked decision) — budget assumes Bybit demo REST RTT is the dominant term; backend-added overhead (validation, idempotency check, per-account fan-out logic for trade groups) budgeted at ≤50ms of the 300ms, leaving ≤250ms for the Bybit demo REST round trip itself (measured, not assumed — validated by the Bybit-connector spike).
- **Live environment**: p95 <500ms target (not a hard gate until R4/pen-test), acknowledging live REST/WS RTT variability is outside CandleViewer's control; the *backend-added* portion budget (≤50ms) is identical to demo and IS a hard, CandleViewer-controlled gate regardless of environment.
- **Trade-group fan-out**: when one ticket fans out to N accounts (up to 5 per capacity model), the ≤50ms backend-added budget is *per-account-parallelized* (concurrent async submission, not serial), so total fan-out backend overhead target stays ≤50ms + a small per-additional-account fixed cost (≤10ms/account for rate-limit-budget bookkeeping) rather than growing linearly and unboundedly with account count — explicitly because Bybit rate limits are per-UID (research finding) and each account's submission is an independent, isolated call.
- **Safety-critical note**: the native exchange-side SL attached to every fanned-out order (locked invariant) is submitted as part of the same budgeted flow, not as a slower "best-effort afterthought" — if the SL-attach call cannot complete within the same ack budget, the parent order is treated as not-yet-safe and the UI reflects a distinct "order live, protective stop pending" state (visible, non-colour-only per the a11y standard) rather than silently reporting a plain "filled" state.

## 6. Ingestion throughput, memory, and storage

### 6.1 Ingestion throughput per symbol (budget #5)

- Backend must sustain, per actively-recorded symbol, the full published Bybit v5 cadence with zero message loss: `publicTrade` (unbounded/bursty, no fixed cadence — sized to historical high-volatility bursts, target ≥500 trade messages/sec/symbol sustained for 60s as the burst-tolerance target, based on observed crypto-perp volatility-event rates), `orderbook.200` (100ms per Bybit's published frequency), `tickers` (~100ms throttled).
- **10-symbol aggregate ingestion target**: the backend ingestion layer must sustain all 10 symbols' streams simultaneously at the above per-symbol rates without cross-symbol interference — achieved via per-symbol async task isolation (one asyncio task/worker per symbol's book-reconstruction + bar-building pipeline), so a burst on one symbol cannot starve another's processing (a direct requirement on the backend architecture in `20-architecture.md`).
- **Zero message loss** is defined and measured as: WS client-side sequence/checksum validation (Bybit orderbook messages carry sequence info) triggering an automatic resubscribe-and-resnapshot on any detected gap, with the gap logged and surfacing as a "recording integrity" flag in the admin/recorder screen — "zero loss" means zero *undetected* loss; detected gaps are self-healed and auditable, which is the realistic, testable definition of this budget (perfect network-level zero-loss is not achievable or meaningfully testable).

### 6.2 Memory ceilings (budgets #7, #8)

- **Frontend** (≤1.5GB/chart workspace): achieved via windowed/virtualized data structures (only visible+prefetch-margin bars materialized at full fidelity; older bars downsampled/summary-only until scrolled into view), the DOM-mirror's own windowing (`05-accessibility-standard.md` §6.1), and bounded per-symbol high-freq state (Jotai atoms capped to a rolling buffer, not unbounded history) — measured via a 2-hour soak test per §7.3 that specifically checks for monotonic growth (leak detection), not just a snapshot at start.
- **Backend** (≤300MB/symbol): achieved via bounded rolling buffers per bar-builder/aggregation engine (e.g. footprint/profile aggregation windows are time-boxed and rolled to storage rather than retained unbounded in process memory), with QuestDB/Parquet as the system of record for anything beyond the in-memory working set — this is a direct constraint on `21-database-schema.md`'s hot-tier design (in-memory state is a cache/working-set, not the durable store).

### 6.3 Storage growth (budget #12)

- **Provisional measurement (E16-K01, `docs/plan/notes/e16-storage-measurement.md`; corpus-derived, live 7-day run pending per #1778 A):** depth-200 BTCUSDT-class ≈ 1.2 GB/day/symbol cold (plausible 0.6-2.4), ≈ 14 GB/day hot; depth 50 ≈ 0.5 cold / 3.9 hot. The 0.75 GB/day planning bound looks ~1.6x low; the budget row is not changed until the live run confirms.

- ~0.75GB/day/symbol compressed at 200-depth (research-sourced estimate) is tracked, not just budgeted-and-forgotten: the admin/recorder screen (View 21-adjacent, per views digest) surfaces per-symbol daily growth and a projected "days until disk full" figure, since recording is user-toggled per symbol (locked decision) and retention defaults to 30 days with pin-to-keep — this is the mechanism that keeps storage bounded in practice without a hard code-level cap, and it's an explicit UI requirement, not just a backend metric.
- **10-symbol worst case** (all symbols recorded continuously, no retention pruning yet triggered): ~7.5GB/day aggregate, ~225GB at 30-day default retention — sized into the capacity plan (§10) as the storage-provisioning basis for the eventual VPS.

### 6.4 Worst-case/stress scenario pass criteria

Under the §3.2 worst-case/stress scenario (all 10 symbols, all 5 users, replay at 100x, synthetic 5x burst for 60s):
- Frame budget #2 (30fps floor) holds throughout, using the degradation strategy in §4.4.
- Ingestion budget #5's "zero *undetected* loss" holds (gaps, if any, are detected/self-healed/logged).
- No backend process OOM-kills or restarts.
- Order submit→ack (on the non-replay, live-trading-simulating portion of the test) does not exceed 2x its normal budget even while the burst is active (i.e. trading responsiveness degrades gracefully, doesn't collapse) — a distinct, explicitly-tested pass criterion because trading correctness/responsiveness under exactly this kind of volatility burst is the entire point of the platform.

## 7. Benchmark harness design

### 7.1 Chart-engine frame-time harness

- A headless/automatable benchmark mode built into the chart-engine package itself (not just ad hoc DevTools profiling): loads a fixed, version-controlled synthetic dataset (100k synthetic OHLCV bars + a synthetic 200-depth heatmap tick stream + synthetic footprint cell data at realistic density, generated deterministically from a seeded script so results are reproducible run-to-run) and drives a scripted sequence of pans/zooms/overlay-toggles/heatmap-updates for a fixed duration (default 5 minutes), recording per-frame timing via the browser's `Performance` API + a custom frame-marker instrumentation matching the §4.3 stage breakdown.
- Runs in: (a) plain headless Chromium (fastest iteration, primary CI target), (b) Electron (release-representative, run nightly not per-PR given startup cost), (c) Tauri/WebView2 during the engine spike only (per the mandatory pre-design-sign-off spike; not a standing CI target once the Electron-vs-Tauri decision is finalized).
- Outputs: p50/p95/p99 frame time overall and per-stage (from §4.3's breakdown), a pass/fail against budget #1/#2, and a flamegraph-style stage-attribution report for the profiling playbook (§9).

### 7.2 Instrumentation

- Frame markers use the browser `Performance.mark()`/`measure()` API at each stage boundary in §4.3, exported as structured spans; backend uses equivalent structured spans (OpenTelemetry-style, feeding the same observability stack as `01-sdlc-and-branching.md`/production Prometheus/Grafana setup) for the WS tick→screen and order→ack budgets, so the *same* trace correlates a single tick or order from Bybit ingestion through to frontend paint end-to-end — this cross-stack correlation (backend span ID propagated to frontend via the WS message envelope) is a specific architecture requirement, not just "have logs on both sides."

### 7.3 Load-test harness (backend/API/WS)

- **k6** (per the brief's test-pyramid requirement) drives REST endpoint load (budget #13) and WS fan-out load (budgets #3, #6) against a staging backend instance connected to **recorded Bybit fixtures** (per the brief's integration-test approach), not live Bybit, so load tests are deterministic and don't consume real rate-limit budget or risk live/demo account state.
- **Locust** (also named in the brief) is used for the higher-level, longer-duration soak scenarios (§6.4's worst-case stress scenario, and the 24h ingestion-soak for budget #5) where Python-native scripting of realistic multi-user/multi-symbol behavioural patterns is more natural than k6's JS scripting.
- **Ingestion soak harness**: a standalone script replays a captured 24h+ Bybit fixture (or a synthetic generator matching real cadence/burst statistics) into the ingestion layer at 1x and at accelerated (10x, for faster iteration) speed, asserting zero-undetected-loss (§6.1) and the memory-ceiling budgets (§6.2) hold over the full duration via periodic sampling.
- **Chart-engine memory soak**: a Playwright-driven session that opens a realistic 4-pane workspace and lets it run for 2 hours under a simulated live-tick generator, sampling process memory every 60s, asserting no monotonic growth beyond a small, documented steady-state variance band (leak detection for budget #7).

### 7.4 CI regression gate (≤5%)

- Every merge to `main` (or nightly, for the more expensive Electron/soak variants) runs the relevant subset of the above harnesses against the current codebase and compares p95 results to a stored baseline (the previous release's or previous week's accepted numbers, checked into the repo or a metrics store alongside the build).
- **Regression gate**: a PR/nightly run that regresses any hard-budget metric's p95 by **more than 5%** relative to baseline fails the build (required check, per `01-sdlc-and-branching.md`'s required-checks model) — mirrors the ≤5% figure requested for this standard. Soft budgets (bundle size, backend CPU, storage growth) alert at the same 5% threshold but do not hard-fail the build; they open a tracked ticket instead, escalated to a hard-fail if 3 consecutive alerts occur without remediation (preventing "boil the frog" drift).
- **Baseline update policy**: baselines only move forward (get stricter or stay flat) via an explicit, reviewed "update performance baseline" PR that includes the harness output and a rationale — a regression cannot be silently "fixed" by just re-baselining without review, which would defeat the gate's purpose.
- **Flake tolerance**: each harness run reports p50/p95/p99 across ≥3 repeated runs per CI execution (not a single sample) specifically to reduce false-positive gate failures from CI-runner noise; the gate compares the median of those repeated p95s, not a single noisy sample.

## 8. Profiling playbook

When a budget is at risk (caught by CI gate, manual QA, or a real usage report):

1. **Reproduce deterministically**: re-run the relevant benchmark harness (§7.1–7.3) locally against the same synthetic dataset/fixture that caught the regression — never start by profiling live/production data if a deterministic repro exists, since it's faster and reviewable in a PR.
2. **Stage-attribute first, then drill in**: use the §4.3 frame-marker stage breakdown (frontend) or the OpenTelemetry span breakdown (backend) to identify *which* stage regressed before profiling within it — this playbook explicitly forbids "just open the Chrome profiler and start guessing" as the first step, since the stage breakdown almost always narrows the search space immediately.
3. **Frontend deep-dive tools** (once a stage is identified): Chrome DevTools Performance panel + `Performance.mark()` correlation, WebGL frame debugger (e.g. Spector.js) for GPU-side stages (heatmap texture upload, candle/footprint draw calls), React DevTools Profiler for any stage that touches React re-renders (should be minimal on the hot path — most hot-path work is deliberately kept outside React's render cycle, in the engine's own imperative draw loop, per the chart-engine design).
4. **Backend deep-dive tools**: `py-spy` (sampling profiler, safe against a running asyncio process) for CPU stages, `memray` for memory-growth stages, structured span timing (already emitted per §7.2) for I/O/await-bound stages (DB writes, Bybit REST calls) — distinguishing CPU-bound from I/O-bound regressions before optimizing the wrong thing.
5. **Fix, then re-run the exact harness that caught it**, confirming the p95 is back within 5% of baseline before closing the ticket — the fix PR includes the before/after harness numbers in its description as evidence, not just "should be faster now."
6. **Postmortem for any hard-budget production-impacting regression**: a short written note (added to a running perf-incidents log referenced from `07-release-and-prr.md`) — what regressed, root cause, why the CI gate didn't catch it earlier (if it shipped before being caught), and what harness/gate change (if any) closes that gap.
7. **Quarterly (or per-major-release) full profiling pass**: even without a triggered regression, the Architect + a rotating engineer run the full worst-case stress scenario (§3.2/§6.4) manually once per release cycle and review all budgets' headroom, specifically looking for slow creeping degradation that stays under the 5%-per-change gate but accumulates over many small changes — the gate protects against big jumps, this pass protects against death-by-a-thousand-cuts.

## 9. Load test scenarios and pass criteria (consolidated)

Every scenario below cites the exact §2 budget row(s) it validates; "Budget #" always refers to the numbered row in the §2 summary table.

| Scenario | Harness | Pass criteria (tied to §2 budget #) |
|---|---|---|
| Nominal load, 60fps sustained | Chart-engine frame harness (headless Chromium) | p95 frame time ≤16.6ms over 5-min scripted run (Budget #1) |
| Realistic peak load, engine | Chart-engine frame harness (Electron, nightly) | p95 frame time ≤16.6ms; p99 ≤22ms (Budget #1, allows brief GC-class hiccups without breaking 60fps perception) |
| Worst-case/stress, engine | Chart-engine frame harness + degradation strategy active | Never drops below 30fps / ≥33.3ms/frame at p99 (Budget #2); degradation strategy (§4.4) engages and is visually verified (manual pass) to show the non-colour-only "reduced detail" indicator |
| DOM heatmap cadence, realistic peak | Frame-timestamp instrumentation on heatmap layer, run concurrently with the engine harness | 100ms visual refresh cadence sustained, ≤1 dropped/coalesced frame per 10s (Budget #14) |
| WS tick→screen | k6 WS load test against staging backend + recorded fixtures, correlated OpenTelemetry spans | p95 <100ms, p99 <250ms sustained over 30-min run at realistic-peak load (Budget #3); backend-internal fan-out sub-span asserted ≤20ms p95 independently (Budget #6) |
| Order submit→ack, demo | k6 scripted order flow against Bybit demo REST (or a recorded-fixture mock for pure backend-overhead isolation) | p95 <300ms end-to-end (Budget #4, demo); backend-added portion isolated and asserted ≤50ms p95 |
| Order submit→ack, live (measured, not gated until R4) | Same harness against Bybit live REST (pen-test-era only) | p95 <500ms end-to-end tracked (Budget #4, live target); backend-added portion ≤50ms p95 remains a hard gate regardless of environment |
| Trade-group fan-out (5 accounts) | k6/Locust scripted fan-out order | Backend-added overhead ≤50ms + ≤10ms/additional account p95 (Budget #4 fan-out sub-clause, §5.2); every fanned-out order's native SL attach completes within the same budget window or the "protective stop pending" state is correctly surfaced |
| Ingestion soak, 24h, 10 symbols | Standalone ingestion soak harness (§7.3) | Zero *undetected* message loss (Budget #5); memory ceiling ≤300MB/symbol p95 holds throughout (Budget #8), no unbounded growth |
| Ingestion burst, synthetic 5x/60s | Ingestion soak harness with burst injector | No dropped/undetected messages (Budget #5); per-symbol task isolation confirmed — other 9 symbols' Budget #3/#6 latency unaffected during the burst |
| Frontend memory soak, 2h | Playwright memory-soak harness (§7.3) | ≤1.5GB steady state (Budget #7), no monotonic growth trend beyond documented variance band |
| Backend memory, per-symbol steady state | Sampled during ingestion soak | ≤300MB/symbol p95 over the 24h run (Budget #8). On the bars soak (`soak_bars`, #399 D2-G4) also a plateau: Theil-Sen slope of the per-symbol RSS over the last 12h ≤0.18MB/h over ≥100 samples ((300−170)MB over 720h, 30 days; MB here is the harness's own unit, a MiB), which for the bars soak is the number for "no unbounded growth" in the soak row above |
| Backend CPU, per-symbol steady state | Sampled during ingestion soak | ≤0.5 vCPU-equivalent p95 per symbol over a 1h steady-state window (Budget #11) |
| Storage growth, 24h × 10 symbols | Sampled during ingestion soak | ≤0.75GB/day/symbol observed delta (Budget #12, upper-bound planning figure) |
| Bundle size | CI bundle-analyzer step, every merge to `main` | ≤8MB gzipped initial bundle (Budget #9); regression >+10% vs. last-tagged baseline fails the soft gate and opens a tracked ticket |
| Startup time, cold launch | Instrumented Electron launch harness, CI + manual on reference hardware | ≤3s cold start → interactive workspace (Budget #10) |
| API load, REST | k6 against staging | Read endpoints p95 <150ms, write endpoints (backend-only portion) p95 <300ms, at 5-concurrent-user realistic-peak load (Budget #13) |
| Replay at 100x | Manual + scripted replay-soak against a recorded 24h fixture | No crash/desync (Budget #15, hard); frame budget floor (30fps, Budget #2) holds or gracefully skip-renders per Budget #15's soft visual-fidelity allowance |
| **Full capacity scenario: 10 symbols / 5 accounts / 5 users, end-to-end** | All harnesses above run concurrently, orchestrated as one composite run against a staging backend provisioned per §10.2's target sizing, for a sustained 2h window | **All of the following hold simultaneously for the full 2h window** (this is the single scenario that validates the capacity plan in §10, not just individual subsystems in isolation): engine p95 frame time ≤16.6ms on each of 5 users' focused panes (Budget #1); DOM heatmap 100ms cadence on ≥2 symbols per user (Budget #14); WS tick→screen p95 <100ms across all 10 symbols × 5 users' 20 pane-subscriptions (Budget #3, §10.1's "20 concurrent pane subscriptions" load driver); order submit→ack p95 <300ms including at least one 5-account trade-group fan-out per test cycle (Budget #4); backend CPU ≤0.5 vCPU/symbol × 10 = ≤5 cores steady-state (Budget #11, §10.2 provisioning basis); backend memory ≤300MB/symbol × 10 = ≤3GB ingestion working set (Budget #8); frontend memory ≤1.5GB per the busiest user's workspace (Budget #7); zero undetected ingestion message loss across all 10 symbols (Budget #5); REST API p95 within Budget #13 under the concurrent 5-user request load; no backend OOM/restart/crash for the full window. Run before each of R1/R2/R3 exit and before the R4 pen-test/PRR gate, per §10.3's re-validation cadence. |
| Full worst-case/stress composite | All harnesses run concurrently per §3.2/§6.4 | All of the above pass criteria hold simultaneously; no backend OOM/restart |

## 10. Capacity planning: 10 symbols / 5 accounts / 5 users

### 10.1 Sizing basis

- **10 symbols**: all budgets in §2/§6 are explicitly sized for 10 simultaneously-recorded symbols as the target scale (matching the Bybit USDT-perp watchlist a small team would realistically track), with the per-symbol async-task-isolation architecture (§6.1) meaning the design scales roughly linearly to this count without a redesign — headroom beyond 10 (e.g. a 6th/7th recorded symbol added later) is expected to degrade gracefully (more CPU/memory/storage consumed, same per-symbol latency budgets) rather than fail catastrophically, though 10 is the tested/gated number, not an unbounded promise.
- **5 accounts**: matches Bybit's own sub-account cap context (5 regular tier / 20 with Business KYC, per research) and the locked "main + sub-accounts, one ticket fans out to N accounts" model; the fan-out latency budget (§5.2) and rate-limit budgeting (per-UID limits, research finding) are sized for 5 concurrent target accounts per trade-group order.
- **5 users**: owner + up to 4 managers concurrently connected (RBAC Owner/Manager/Viewer, locked decision); WS fan-out and REST load budgets (§2 #3, #6, #13) are sized for 5 concurrent sessions each potentially viewing a 4-pane multi-symbol layout — i.e. up to 5 × 4 = 20 concurrent "pane subscriptions" fanned out per relevant symbol/topic combination, which is the real multiplicative load driver the backend fan-out layer (§5.1) must handle, not just "5 users" as a flat number.

### 10.2 Resource provisioning target (backend VPS, the eventual production home)

| Resource | Target provisioning | Basis |
|---|---|---|
| vCPU | 4-6 cores | 10 symbols × ≤0.5 vCPU/symbol (budget #11) = ≤5 cores steady-state, + headroom for OMS/API/admin request handling and burst scenarios |
| RAM | 8-16GB | 10 symbols × ≤300MB/symbol (budget #8) = ≤3GB for ingestion/aggregation working set, + Postgres/QuestDB buffer-pool/cache needs, + OS/container overhead, + headroom for burst-scenario transient growth |
| Disk (hot, QuestDB) | Sized to ~30-day default retention window | 10 symbols × ~0.75GB/day (budget #12) × 30 days ≈ 225GB, provisioned with margin (target 400-500GB SSD) to allow pinned/longer-retention symbols and avoid emergency pruning under time pressure |
| Disk (cold, Parquet archive) | Separate, cheaper-tier storage, sized for multi-year archive of pinned/important symbol-days | Sized per actual pin usage once observed in R1-R2; not a hard number at planning time, tracked via the admin storage dashboard (§6.3) |
| Network | Tailscale overlay only; no public ingress | Locked decision; no internet-facing load-balancing/CDN capacity planning needed |

### 10.3 Growth headroom and re-planning triggers

- This capacity plan is re-validated (not just assumed to hold) at each of: R1 exit (chart-engine spike results), R2 exit (order-flow engines under real multi-symbol load), R3 exit (first real demo-trading multi-account fan-out under load), and before R4 (Live enablement) as part of the pen-test/PRR gate in `07-release-and-prr.md`.
- **Re-planning triggers** (any of these means this section's numbers must be revisited before proceeding): recorded-symbol count trending toward >10 as a steady habit (not occasional), sub-account count growing toward Bybit's Business-KYC 20-cap tier, concurrent-user count growing beyond 5, or any hard-budget CI gate (§8) failing repeatedly at the *current* target scale even after the profiling playbook (§9) has been exhausted (signalling the architecture, not just the code, needs to change).
- **Explicitly out of scope for this capacity plan**: multi-tenant SaaS scaling, horizontal backend scale-out, CDN/edge considerations, and any Android/mobile client capacity — all excluded per the locked scope decision; if a future mobile client is added (kept possible via the client-agnostic protocol requirement), it would be re-planned as a new, additive load source at that time, not retrofitted into these numbers now.

<!-- prettier-ignore-end -->

## 11. Cross-references

- `05-accessibility-standard.md` — DOM-mirror/live-region throttling shares the same frame-budget discipline (§4.1, §6.2 of this doc); the "reduced live detail" degradation indicator (§4.4) must satisfy the colour-independence rule.
- `01-sdlc-and-branching.md` — CI required-checks model that hosts the ≤5% regression gate (§8).
- `03-testing-strategy.md` — k6/Locust load tests, engine FPS benchmarks, and ingestion soak tests are named test-pyramid layers; this document is their concrete spec.
- `07-release-and-prr.md` — capacity re-validation and pen-test-era live-latency re-measurement are PRR gate inputs.
- `20-architecture.md` — per-symbol async task isolation, backend fan-out design, and hot/cold storage tiering are architecture requirements directly driven by §6/§10 of this document. **Tracking note**: `20-architecture.md` does not yet exist; once written, validate that its design actually satisfies the §10.2 provisioning targets and the per-symbol isolation assumption underlying §5.1/§9's fan-out latency budgets — this is a required cross-check before R1 exit, not just a documentation nicety.
- `21-database-schema.md` — hot-tier (QuestDB) working-set-vs-durable-store boundary (§6.2) and retention/disk sizing (§10.2) are binding constraints on the schema/retention design.
- `26-chart-engine-design.md` — the frame-budget breakdown (§4.3), windowed/virtualized data model (§4.1), DOM-mirror sync cost budget, and degradation strategy (§4.4) are binding engine-design requirements.
