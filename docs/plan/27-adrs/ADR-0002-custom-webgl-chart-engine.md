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

## O2 atlas configuration, re-confirmed with real font rasterisation — 2026-10-31

Amendment by E11-K01 (#332). E06-K03 closed O2 on a procedural stand-in rasteriser (`spikes/E06-K03.md`
"Honest limits"). E11-K01 re-measures it in headless Chromium with OffscreenCanvas `fillText`, the real
IndexedDB and a SwiftShader WebGL2 context. The record is `docs/plan/spikes/E11-K01.md`; its figures live in
`E11-K01-results.json`, and this section repeats none of them.

- **Parameterised on the font.** The family choice is final (`16` §2.2, owner decision 2026-09-25), but the
  font files are not vendored yet and no ticket vendors them (G-42), so the recorded run used named
  stand-in files. The harness reads the shipped variable WOFF2 files as they ship, so once they are vendored
  the rerun is one command on the bytes the cache key hashes (`spikes/E11-K01-harness/README.md`); a rerun
  on TTF builds counts only when their version string matches. A rerun that changes a decision below is
  recorded as a further amendment here.
- **Families:** JetBrains Mono 400 for cell text, axis ticks and GL pills; Inter 600 for the watermark
  (E11-D02 D13). Both share **one R8 texture**, so the axis batch binds one texture (BQ-171).
- **Glyph set:** printable ASCII (U+0020–U+007E) for each family, plus `×`, `▲`, `▼` (mono) and `·` (Inter):
  194 glyphs (BQ-172). A glyph the font lacks is taken from the other family when it has it, else the set
  is rejected (BQ-180). An out-of-set character draws `?` from the same family and trips a dev assertion.
  The atlas never grows at runtime (BQ-181).
- **Atlas size: 1024×1024, 1 MiB**, a stated deviation from the ticket's "smallest size that meets every
  gate" rule, which cannot select while no size meets the cold gate (inconclusive here). Every candidate
  packs all 194 glyphs; 512² has about 1.7× height headroom and 1024² about 6.6×. E11-S11 re-applies the
  rule on the shipped fonts, and 512² wins if it meets every gate (BQ-173).
- **Raster sizes:** mono 24 px with spread 4, Inter 32 px with spread 6 (BQ-174). There is **one raster per
  family**. The 24 px mono base is **provisional**: the 16 px base met the pair-ratio gate in more of its
  measured cases, so E11-S11 chooses between 24 px, 16 px and two mono rasters by the rule in the spike note
  ("Requirements" item 7). Size classes 0 / 1 / 2 and DPR are shader scales, so a DPR change never regenerates the atlas
  (BQ-175).
- **Packer:** shelf, sorted by height then codepoint. 1024² never overflowed, so no skyline packer was tried
  (BQ-183).
- **Cache:** the IndexedDB key covers family, font-bytes SHA-256, weight, raster size, spread, glyph-set
  hash, atlas size and generator version (BQ-176). The record stores only the packed rows, not the whole
  texture, which is what brings the warm read near the B9 secondary gate.
- **Shader:** §3.7's `fwidth` band. It beat the shipped fixed 0.45–0.55 band on median SSIM and on the worst
  cell glyph in all nine measured cases; the fixed band separated the closest pair better in three
  (BQ-184, C-56).
- **Open, under the #220 evidence rule:** cold generation and the computed legibility proxies miss their
  gates on this below-class, contended host. That is inconclusive, not a rejection: E11-S11 re-measures
  them on the shipped fonts with pass/fail rules (spike note, "Requirements" items 5–9). MSDF was not
  evaluated: its trigger moves to E11-S11's K3 A/B, the owner's call on the packet E11-S11 renders, and
  11 px dpr 1 does fail the proxies. That MSDF would not restore hinting under minification is
  `(heuristic)`: argued, not measured.
- **Open interpretation, not decided here:** whether the 60 ms cold gate excludes the font load and the
  worker spawn. A cache hit avoids the bytes-to-`FontFace` load but not the font-bytes fetch and hash for
  the key; E11-S11 K2 reports the figure both ways, and the architect and the orchestrator decide.
