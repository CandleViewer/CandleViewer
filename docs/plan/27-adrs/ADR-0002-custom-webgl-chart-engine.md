# ADR-0002 — Custom WebGL chart engine

- Status: **decided**
- Date: 2026-09-14
- Deciders: Owner (basiltt), Architect, Chart-engine lead, Chief Design Officer
- Consulted: `docs/research/10-frontend-tech.md`, `docs/research/22-architecture-options.md` §5, `docs/research/24-owner-decisions.md` decision #1, digests 01, 04, 05, 23
- Related: `docs/plan/26-chart-engine-design.md`

## Context and problem statement

Every differentiating surface in CandleViewer needs rendering that no charting library ships: footprint cells with per-cell text at high density, volume/delta profiles and TPO, a DOM liquidity heatmap updating every 100 ms over hours of history, big-trade bubbles, draggable order/position lines across multiple accounts, and a drawing-tool kit. Research surveyed 16 candidate libraries and found **none** provides footprint, heatmap or DOM natively; all routes require substantial custom rendering. The question is whether to build on a chassis (Lightweight Charts v5) or to build the whole engine.

## Decision drivers

- Owner explicitly chose "best feature-rich" over lowest effort (owner decision #1).
- Pixel-level control is needed for the majority of the surface area anyway.
- This is a long-lived personal platform; a chassis's constraints would compound over years.
- Anti-lock-in: no proprietary or approval-gated dependency.
- Research effort estimate: chassis route ≈ 11–17 weeks of custom rendering regardless; fully custom adds ≈ 4–8 weeks to reach chassis parity (pan/zoom momentum, axis decimation, multi-pane sync, crosshair, DPI correctness).

## Considered options

1. **Fully custom WebGL2 engine** in `packages/chart-engine`.
2. **Lightweight Charts v5 chassis** + custom series/primitives + a separate WebGL heatmap layer (the research report's original recommendation).
3. **KlineCharts v9/v10 chassis** — ships a drawing-tools toolbar and a drag-capable overlay system.
4. **LightningChart JS Trader** (commercial, ~$4,900/yr first dev, quote-gated) — native WebGL heatmap.
5. **TradingView Advanced Charts** — richest chassis, proprietary and approval-gated.

## Decision outcome

**Chosen: option 1 — a fully custom WebGL2 engine**, designed in `26-chart-engine-design.md`, with **option 2 retained as the documented fallback**.

Key structural commitments that make the fallback cheap:
- The engine's data model (`BarStore`, `FootprintStore`, `HeatmapRing`, `ProfileStore`) and its plugin API are defined independently of the renderer, so footprint/heatmap/profile layers can be re-hosted onto Lightweight Charts primitives without a rewrite.
- Milestone M1 ("chassis parity") is scheduled and benchmarked *first*, so the riskiest unknown is resolved before any order-flow feature depends on it.
- A `degraded-2d` Canvas 2D mode is a supported, tested profile, not an accident — it also serves as the parity reference implementation.

### Fallback trigger (binding)

The fallback to option 2 is adopted if **either**: spike S1 (M0) fails its exit criteria (100k candles + 2,500 footprint text cells + 100 ms heatmap at the documented p95 frame times on the reference machine, in Chromium and Electron), **or** milestone M1 overruns its 6-engineer-week estimate by more than 50 %. The decision is the Architect's, recorded as an amendment to this ADR.

### Consequences

Positive:
- Complete control over footprint text density, heatmap streaming, LOD behaviour and interaction feel — the three surfaces that define the product.
- One rendering model for every layer, instead of a chassis plus a bolted-on WebGL layer with two coordinate systems to keep in sync (a real source of bugs in the option-2 design).
- No licence, no NOTICE obligations, no approval dependency.
- A WebGPU backend is a contained future change (`RenderBackend` interface).

Negative / risks:
- Highest effort of all options (≈ 33 engineer-weeks for the engine squad) and the single largest schedule risk in the project.
- We own bugs that a chassis would have solved (DPI edge cases, trackpad wheel semantics, momentum feel, axis decimation aesthetics). Mitigated by making M1 explicitly about parity, with golden-image and property tests.
- Graphics-capable headcount is a bus-factor concern. Mitigated by pairing on the engine squad, mandatory design docs per milestone, and CI benchmarks that make regressions visible to anyone.

### Why not the alternatives

- **Lightweight Charts v5 chassis**: saves the parity weeks but constrains exactly the two surfaces that matter most (dense cell text and a 100 ms heatmap), and forces a second coordinate system for the WebGL heatmap layer. Kept as the fallback precisely because it is credible.
- **KlineCharts**: saves the drawing-tools kit (1–2 weeks) but has a smaller ecosystem, a disruptive v9→v10 migration history, and still gives us neither footprint nor heatmap.
- **LightningChart JS Trader**: solves the heatmap natively but introduces a recurring cost and a second proprietary dependency, cutting against the project's explicit values; footprint remains fully custom either way.
- **TradingView Advanced Charts**: approval-gated, non-redistributable, and Pine Script's `request.footprint()` is not exposed outside the consumer product — it does not actually solve our problem.

## Validation

- Spike S1 / milestone M0 report with measured p95 frame times across Chromium, Electron and Tauri/WebView2.
- M0 findings report (E06-T02): `docs/plan/spikes/E06-M0-report.md` — verdict §2, fallback trigger §3.3.
- CI performance gates B1–B10 in `26-chart-engine-design.md` §13 as required checks on the package.
