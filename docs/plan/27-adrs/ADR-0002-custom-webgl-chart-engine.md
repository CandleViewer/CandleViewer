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
- Milestone M1 ("chassis parity") is scheduled and benchmarked _first_, so the riskiest unknown is resolved before any order-flow feature depends on it.
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

## M0 outcome — 2026-10-29

Amendment by E06-T03 (#222). The text above is the record as decided on 2026-09-14 and is unchanged. The
evidence is the M0 findings report, `docs/plan/spikes/E06-M0-report.md` (E06-T02), whose generated tables are
the only source of figures; this section cites their sections and rows and repeats none of them.

- **Decision:** the Architect's, as the fallback trigger requires — recorded under the orchestrator's
  delegation (#220, 2026-10-29 08:40Z); Architect / Security-engineer sign-off comments pending on #222.
- **Outcome: the fallback trigger did not fire. Option 1, the custom WebGL2 engine, is confirmed; the
  Lightweight Charts v5 chassis stays the documented fallback and is not adopted.**

### Evidence class

Every matrix figure was measured on one host below the `06` §3.1 reference class (report §1, machine row in
§5). The ruling of #220 (2026-10-29 08:40Z) sets the evidence rule: a budget **met** on that host is
conservative evidence that it holds on the reference class; a budget **missed** there is inconclusive and is
re-measured on reference hardware. The owner's attended reference run is a post-GA confirmation line, not a
gate. The Tauri / WebView2 arm was dropped by the same ruling (ADR-0011's decision of the same date).

### The trigger, half by half

1. **Half 1 — M0 exit criteria: does not fire (conservative).** B1, B3, B4 and B5 meet their p95 gates in
   both headless Chromium and Electron (report §3.3, row "Trigger half 1"; verdict §2 V2). The same run is R0
   exit criterion 4's evidence: **PASS on the conservative reading** (report §2 V1, §3.2 row "Electron").
   The roadmap's wording is "on reference hardware in Electron" (`30-release-roadmap.md` §4.3 item 4); the
   reference-hardware run is the post-GA confirmation line above, so this PASS rests on the ruling's
   evidence rule, not on a reference-class measurement.
2. **Half 2 — M1 overrunning its 6-engineer-week estimate by more than 50 %: still live.** It is a schedule
   fact, not a measurement, and M0 cannot settle it (report §2 V2). It stays binding until M1 (E11) closes;
   the Architect assesses it then against M1's actual effort, and if it fires, the decision is recorded as a
   further amendment here.

### What M0 does not establish

- **A harness, not the engine.** The verdicts rest on the spike's harness page (a fixed WebGL2 load plus
  modelled scene costs), not the production engine; E11 re-establishes them on the real engine (report §1,
  §2 V3, §10).
- **Inconclusive, re-measure:** B10's resident-memory peak and its start-to-end growth missed their gates
  on the below-class host (report §2 V5, §3.5 row "Electron"). Under the evidence rule they decide nothing
  here; E11 treats memory as a real budget (U2 below).
- **A hitch that p95 hides:** the B5 footprint rebuild produces frames over 33 ms in every run (report §2 V6,
  §3.2 column "Frames > 33 ms"). Neither the trigger nor criterion 4 can see it (both are p95 bars); M3 must
  chunk the rebuild (report §10 M3).
- **Shelf life:** the figures belong to the runtime, driver and Node versions in the report's §5 manifest
  (Electron 45 / Chromium 156). A Chromium or driver bump can move them, which is why the recording-only CI
  job keeps measuring (report §5 "Shelf life", §12). The hosted-runner CI numbers are software GL and are
  regression tracking only, never reference-hardware evidence (report §5, §12).

### Engine path confirmed

The custom engine proceeds as designed in `26-chart-engine-design.md`. The text strategy is the SDF atlas
(report §6, E06-K03), the heatmap coarse ring is provisionally decided (report §7, E06-K04), and §10 of the
report states what each milestone M1–M8 must budget. The structural commitments that keep the fallback cheap
(renderer-independent data model and plugin API, M1 first, a tested `degraded-2d` profile) stay in force
while half 2 of the trigger is live.

### Open items carried (report §11)

| Item | What is open                                           | Owner                    | Resolution path (report §11)                         |
| ---- | ------------------------------------------------------ | ------------------------ | ---------------------------------------------------- |
| U1   | Every matrix figure is from a below-class host         | Owner / QA               | Reference-hardware re-measure, post-GA line          |
| U2   | B10 memory peak and growth missed (inconclusive)       | Chart-engine lead        | Real engine on reference hardware (E11-S15, E11-Q03) |
| U3   | B7 frame p95 not recorded                              | Chart-engine lead        | E11-T06 keeps it in the report cell                  |
| U4   | Stage split beyond mirror and upload not recorded      | Chart-engine lead        | E11-T07, E11-T06                                     |
| U5   | SwiftShader stalls on the Chromium arm                 | QA                       | E11-T06 (#449)                                       |
| U6   | No GPU in CI; hosted-runner numbers are software GL    | Architect                | Dedicated GPU runner: E03-T14 / E11-T06              |
| U7   | Q02 hardware cells and the `degraded-2d` renderer      | QA                       | E11-Q07 (#519); E11-T05 (#522)                       |
| U8   | B5 co-tenancy variant not run                          | Chart-engine lead        | E11-Q03, once the dev stack and engine exist         |
| U9   | The D03 mirror bench in Electron on reference hardware | Chart-engine lead + a11y | E11-S13 (#520); E11-Q03 (#445) signs it off          |

U1 is a post-GA line (the owner's attended reference run); U2–U9 are E11 work, with U6's GPU runner
shared with E03-T14.

No R1 re-cut follows: the fallback did not fire (`30-release-roadmap.md` §4.3 item 4). The E11 tickets that
inherit these findings are listed in the report's §13 and are commented on after merge (filing freeze: no new
tickets).
