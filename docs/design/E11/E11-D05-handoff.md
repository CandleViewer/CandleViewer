# E11-D05 — Per-component handoff checklist (`16` §11.4)

Nine blocks (one per chart primitive; every line of the `16` §11.4 block kept), then Tables 1–5, the Density table and the Essential-exceptions table **once each with a leading `Component` column** so every component's rows are present without nine copies (deviation recorded in `E11-D05.md` §16 item 6; the fallback is per-component tables, then `large-pr-approved`). The Density table carries three chart densities (comfortable / compact / dense — E11-D02 D6, `E11-D05.md` §6), a deviation from the template's two, stated. The Penpot line follows the page-ref rule (page **name + id**; never a hostname, team or file id, or a workspace URL — `E11-D05.md` C19; E25-D05 CR-6) and names the drawn page `E11-D05` · id `0bde4016-6d2e-8002-8008-d42e063e55da` (boards 01–08 drawn and exported, spec §0; boards 09 / 10, the ref frames, drawn and exported on page `E11-D05 ref frames` · id `cb0c3916-2579-81a4-8008-debf597b2f21` in the per-set file `E11-D05 ref frames`, spec §0 / §18; the DS library entry routes to E11-T04 #390, spec §15). CMP-039 gets no block: it is E05's atom and this ticket appends one usage paragraph to its `15` entry (`E11-D05.md` §9.1). Spec: `docs/design/E11/E11-D05.md`; tokens: `packages/ui/tokens` at `ced9a352b2785715ebe8ec74b3fd66443ed7ee05`; matrix: `docs/design/_tools/e11_d05_ds_audit.py`.

## Handoff checklist — CMP-180 ChartRoot (E11-D05, #310)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link — page + PNG** — page `E11-D05` · id `0bde4016-6d2e-8002-8008-d42e063e55da`; PNG at `docs/design/E11/img/E11-D05-01-slot-map.png` and `docs/design/E11/img/E11-D05-06-primitives-matrix.png`
- [x] **Final Penpot link — ref frames** — the ref frames `CMP-180 · ChartRoot — ref frame (<state>)` on board 09 `ref-frames-a` (id `0c4baecb-5183-80d0-8008-df897051bf16`, export `docs/design/E11/img/E11-D05-09-ref-frames-a.png`), page `E11-D05 ref frames` · id `cb0c3916-2579-81a4-8008-debf597b2f21` in the per-set file `E11-D05 ref frames` (spec §0 / §18; never the DS library file); the DS library entry routes to E11-T04 (#390)
- [x] **Variants × States matrix** — boards 01–08 drawn — spec §0; one ref frame per state on board 09 `ref-frames-a`, drawn 2026-10-30, spec §18; the full product is not drawn — the text is binding, RULED (orchestrator, #310 2026-10-30 12:09Z) Q2: 2 variants (single / multi pane) × 10 states (E11-D02 D16; spec §8.1); Table 1
- [x] **Keyboard table** — the chart region's Tab order (toolbar → status chips → per pane: legend → left gutter → plot → handles → right gutter → lock badge → splitter; `Ctrl+\` leaves) and the plot cursor keys (E11-D02 §12; E06-D03 D5 / D6); no view-local override of a global binding, `Esc` / `Ctrl+K` untouched; Table 2
- [x] **Accessible name / role table** — canvas `role="img"` with the rolling label; the wrapper's role open (E11-D07, spec Q8); the mirror root; the two live regions (E11-D02 §10); Table 3
- [x] **Live data** — the canvas label and the ambient region polite ≤1 per 2 s per field; `role="alert"` for context lost / restored, stale, LOD step-down (E11-D02 §10); the `a11y` / `viewport` messages ≤1 per frame; Table 5
- [x] **Motion pair** — the stale dim (E11-D06 D13: data-ink × 0.85 over `motion.duration.normal`, instant under reduce); chips and badges are state flips (D15); the skeleton shimmer static under reduce (D16); Table 4
- [x] **Density notes** — three chart densities (E11-D02 D6 / §2): rows 32 / 24 / 24, legend inset 12 / 8 / 4, `cellPadPx` 4 / 2 / 1; the smallest target 24 × 24 in every mode (`size.target.min`); Density table
- [x] **Essential-exceptions log** — none (dense never shrinks a target below 24 px, D6 rule 3)
- [x] **Tokens used** — `color.chart.pane.bg.default`, `color.chart.pane.bg.focused`, `color.chart.grid.major`, `color.chart.grid.minor`, `color.chart.replay.border` (PROPOSED slots, spec §4), `color.focus.ring`, `color.surface.raised`, `color.text.primary`, `color.status.warning.strong` = the `15` CMP-180 Tokens field; none invented; Penpot token sets = `packages/ui/tokens` at `ced9a352b2785715ebe8ec74b3fd66443ed7ee05`
- [x] **Data contract confirmed** — the `26` §6 messages (`init`, `resize`, `command`, `frame`, `viewport`, `a11y`, `error`); market data from `bars.{symbol}.{bar_type}.{param}` and `ticker.{symbol}` (`14` §0.4); `viewport.lod` is a gap (spec G2)
- [ ] **Contrast and CVD** — PENDING (the PROPOSED `pairs.mjs` rows are registered by the token PR, spec CR-5, and the gate is green only then; CVD run on the exports 2026-10-22, spec §10.3 — PASS): spec §10.1: pane fill vs chrome rows 1.06 / 1.07 / 1.06 (a surface), major grid 1.50 / 1.31 / 3.03 and minor 1.15 / 1.17 / 1.15 (decorative by design), replay frame 6.73 / 5.60 / 6.73, badge text 14.35 / 15.62 / 16.25, badge glyph 11.00 / 4.11 / 11.00, the ring 7.05 / 6.30 / 18.32 — all gated rows PASS; CVD: replay border vs ring collapses under deuteranopia in dark (2.2, carried by width, chip and clock); `cvd_sim.py` run on the exports (spec §10.3: the collapse shows in board 02's deuteranopia render as computed; the 4 px width and the labelled row carry it)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — CMP-188 PriceAxis (E11-D05, #310)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link — page + PNG** — page `E11-D05` · id `0bde4016-6d2e-8002-8008-d42e063e55da`; PNG at `docs/design/E11/img/E11-D05-02-token-slots-three-themes.png` and `docs/design/E11/img/E11-D05-06-primitives-matrix.png`
- [x] **Final Penpot link — ref frames** — the ref frames `CMP-188 · PriceAxis — ref frame (<state>)` on board 09 `ref-frames-a` (id `0c4baecb-5183-80d0-8008-df897051bf16`, export `docs/design/E11/img/E11-D05-09-ref-frames-a.png`), page `E11-D05 ref frames` · id `cb0c3916-2579-81a4-8008-debf597b2f21` in the per-set file `E11-D05 ref frames` (spec §0 / §18; never the DS library file); the DS library entry routes to E11-T04 (#390)
- [x] **Variants × States matrix** — boards 01–08 drawn — spec §0; one ref frame per state on board 09 `ref-frames-a`, drawn 2026-10-30, spec §18; the full product is not drawn — the text is binding, RULED (orchestrator, #310 2026-10-30 12:09Z) Q2: 2 gutters × 3 densities × 8 states (E11-D02 D7; spec §8.2); Table 1
- [x] **Keyboard table** — `↑/↓` 10 %, `Shift+↑/↓` 25 %, `PageUp/PageDown` pan 50 %, `Home` auto-fit, `Shift+F10` menu, `Esc`, `Tab` to the lock badge (E11-D02 §7.1); no global conflict (axis-scoped); Table 2
- [x] **Accessible name / role table** — surrogate `role="group"` "Price axis, 63,900 to 64,300, linear, auto"; the lock badge a button named by its text; Table 3
- [x] **Live data** — the last-price pill per tick with no flash, its colour held ≤2/s; tick labels in the mirror ≤1 per frame; announcements polite ≤2/s; Table 5
- [x] **Motion pair** — a keyboard rescale is one frame in both modes (E11-D06 D11); the pill colour change is a flip; Table 4
- [x] **Density notes** — axis type `type.num.base` / `sm` / `xs`, gutter padding 8 / 4 / 4, density gap `G` 48 / 40 / 32 px, pill 20 / 17 / 16 px; the gutter ≥48 px wide, target 24 px floor; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.chart.axis` (PROPOSED slot = `color.text.tertiary`), `font.family.mono` via `type.num.xs` / `type.num.sm` / `type.num.base`, `type.ui.caption`, `color.chart.rule`, `color.candle.up` / `color.candle.down` + `color.chart.pill.text.inverse`, `color.chart.pill.bg` + `color.chart.pill.border` + `color.chart.pill.text.default` (the GL pills — PROPOSED spec §4.1b aliases of `color.border.default`, `color.text.inverse`, `color.surface.raised` / `color.border.strong` / `color.text.primary`), `color.surface.raised` + `color.border.strong` + `color.text.primary` (the lock badge), `color.chart.boundary` (the mark line), `color.focus.ring` = the `15` CMP-188 Tokens field; `font.mono` retired (spec G1); Penpot token sets = `packages/ui/tokens` at `ced9a352b2785715ebe8ec74b3fd66443ed7ee05`
- [x] **Data contract confirmed** — `viewport { priceLow, priceHigh }`; mark / index from `ticker.{symbol}`; tick size from `GET /api/v1/instruments/{symbol}`
- [ ] **Contrast and CVD** — PENDING (the `color.chart.axis` row at TEXT and the pill rows are PROPOSED `pairs.mjs` rows, spec CR-5; CVD run on the exports 2026-10-22, spec §10.3 — PASS): spec §10.1: axis labels 5.96 / 6.36 / 11.87 (the hc 7:1 bar holds), pill text on the up fill 7.87 / 5.39 / 7.87 and on the down fill 4.94 / 5.20 / 4.94, mark line 5.96 / 6.36 / 11.87, neutral pill text 14.35 / 15.62 / 16.25 — PASS; CVD: up vs down 8.3 under deuteranopia in dark (the glyph carries direction)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-189 TimeAxis (E11-D05, #310)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link — page + PNG** — page `E11-D05` · id `0bde4016-6d2e-8002-8008-d42e063e55da`; PNG at `docs/design/E11/img/E11-D05-05-pattern-registry.png` and `docs/design/E11/img/E11-D05-06-primitives-matrix.png`
- [x] **Final Penpot link — ref frames** — the ref frames `CMP-189 · TimeAxis — ref frame (<state>)` on board 09 `ref-frames-a` (id `0c4baecb-5183-80d0-8008-df897051bf16`, export `docs/design/E11/img/E11-D05-09-ref-frames-a.png`), page `E11-D05 ref frames` · id `cb0c3916-2579-81a4-8008-debf597b2f21` in the per-set file `E11-D05 ref frames` (spec §0 / §18; never the DS library file); the DS library entry routes to E11-T04 (#390)
- [x] **Variants × States matrix** — boards 01–08 drawn — spec §0; one ref frame per state on board 09 `ref-frames-a`, drawn 2026-10-30, spec §18; the full product is not drawn — the text is binding, RULED (orchestrator, #310 2026-10-30 12:09Z) Q2: 3 densities × 9 states (E11-D02 D8; spec §8.3); Table 1
- [x] **Keyboard table** — `←/→` pan 10 % (`Shift` one width), `+/−` × 1.1 (`Shift` × 1.25), `Home` fit, `End` latest, `Ctrl+Home` default spacing, `Shift+F10`, `Esc`; the cluster's `←/→` + `Enter` / `Space` (E11-D02 §7.2); no modifier + wheel is bound (E11-D01); Table 2
- [x] **Accessible name / role table** — surrogate `role="group"` "UTC time axis, 14 Oct 07:30 to 13:47, 1 minute bars"; the `auto` button named by its visible text; the zone tag `aria-live="off"`; Table 3
- [x] **Live data** — the zone tag's clock at 1 Hz off; "Paused at hh:mm" once on pausing; the retained labels in the mirror ≤1 per frame; Table 5
- [x] **Motion pair** — `fit` / `›` jumps animate ≤ `motion.duration.normal` under motion and cut under reduce (E11-D06 D7); the Paused pill is a flip (D15); Table 4
- [x] **Density notes** — strip 32 / 24 / 24 px, `G` 96 / 80 / 64 px, cluster segments 32 / 24 / 24; the smallest target 24 × 24; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.chart.axis`, `font.family.mono` via `type.num.*`, `color.chart.rule`, `color.chart.boundary`, `color.chart.hatch.texture` (PROPOSED spec §4.1b aliases of `color.border.default`, `color.text.tertiary`, `color.border.strong`), `color.surface.raised`, `color.border.default`, `color.surface.selected`, `color.border.strong`, `color.text.primary`, `color.status.warning.subtle`, `color.status.warning.strong`, `color.surface.hover`, `color.text.secondary`, `color.chart.marker.goto` + `color.chart.pill.text.on-marker` (aliases of `color.action.primary.default` / `color.text.on-action`), `color.chart.crosshair`, `opacity.muted`, `color.chart.replay.border`, `opacity.scrim`, `color.focus.ring` = the `15` CMP-189 Tokens field; pattern ids `pattern.hatch.gap`, `dash.4-4` (spec §7); Penpot token sets = `packages/ui/tokens` at `ced9a352b2785715ebe8ec74b3fd66443ed7ee05`
- [x] **Data contract confirmed** — `viewport { timeStart, timeEnd, barSpacing }`; `sync { groupId, timeRange }`; boundaries from the instrument / system feed; the server clock (E11-S07)
- [ ] **Contrast and CVD** — PENDING (PROPOSED `pairs.mjs` rows, spec CR-5; CVD run on the exports 2026-10-22, spec §10.3 — PASS): spec §10.1: boundary line and band edges 5.96 / 6.36 / 11.87, hatch texture 1.91 / 1.57 / 1.91 (decorative; the edges and the label carry the band), pressed `auto` text 10.17 / 12.82 / 11.51, Paused text 9.86 / 15.62 / 11.16 and glyph 7.56 / 4.11 / 7.56, go-to-date marker 3.85 / 4.44 / 7.05, remote crosshair 5.12 / 4.17 / 5.12 — PASS; greyscale: boundary by dash, band by hatch (spec §10.3)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-190 Crosshair (E11-D05, #310)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link — page + PNG** — page `E11-D05` · id `0bde4016-6d2e-8002-8008-d42e063e55da`; PNG at `docs/design/E11/img/E11-D05-02-token-slots-three-themes.png` and `docs/design/E11/img/E11-D05-06-primitives-matrix.png`
- [x] **Final Penpot link — ref frames** — the ref frames `CMP-190 · Crosshair — ref frame (<state>)` on board 09 `ref-frames-a` (id `0c4baecb-5183-80d0-8008-df897051bf16`, export `docs/design/E11/img/E11-D05-09-ref-frames-a.png`), page `E11-D05 ref frames` · id `cb0c3916-2579-81a4-8008-debf597b2f21` in the per-set file `E11-D05 ref frames` (spec §0 / §18; never the DS library file); the DS library entry routes to E11-T04 (#390)
- [x] **Variants × States matrix** — boards 01–08 drawn — spec §0; one ref frame per state on board 09 `ref-frames-a`, drawn 2026-10-30, spec §18; the full product is not drawn — the text is binding, RULED (orchestrator, #310 2026-10-30 12:09Z) Q2: 1 variant × 6 states (E11-D02 D3 / D9; spec §8.4); Table 1
- [x] **Keyboard table** — `←/→` bar, `Shift` ×10 (= `PageUp/PageDown`), `↑/↓` level, `Home/End`, `Enter` expand (E06-D03 D5 / D6; E11-D02 §7.3); Table 2
- [x] **Accessible name / role table** — the focused bar's mirror row carries `aria-current`; the pills are GL text, the mirror and the live region carry the values; Table 3
- [x] **Live data** — the cursor announcement per E06-D03 D5 (lead 0 ms, repeat window 500 ms, trailing flush ≤250 ms); pointer moves are never announced; Table 5
- [x] **Motion pair** — the position never eases in either mode (E11-D06 D9); the appear is 0 ms, the leave fades `motion.duration.fast` → instant; Table 4
- [x] **Density notes** — pill height 20 / 17 / 16 px, `type.num.*` per density; the keyboard cursor column ≥2 px; the target is the plot stop; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.chart.crosshair` (PROPOSED slot = `color.crosshair`), `color.chart.pill.text.inverse`, `color.chart.pill.bg` + `color.chart.pill.border` + `color.chart.pill.text.default`, `opacity.muted`, `color.chart.focus.ring` + `color.chart.pane.bg.default` (the cursor column on the canvas — PROPOSED spec §4.1b aliases of `color.text.inverse`, the neutral pill tokens, `color.focus.ring` / `color.surface.canvas`), `type.num.*`, `radius.xs` = the `15` CMP-190 Tokens field; dash id `dash.4-4`; Penpot token sets = `packages/ui/tokens` at `ced9a352b2785715ebe8ec74b3fd66443ed7ee05`
- [x] **Data contract confirmed** — `pick { objectId, kind, bar, price, cell? }`, `a11y { cursorSummary }`, `sync { crosshair }` (`26` §6); `ChartEvents["crosshair"]` edge-triggered
- [ ] **Contrast and CVD** — PENDING (the `color.chart.crosshair` rows over the gridlines are PROPOSED `pairs.mjs` rows, spec CR-5; CVD run on the exports 2026-10-22, spec §10.3 — PASS): spec §10.1: lines 9.33 / 9.65 / 9.33, over the major line 6.24 / 7.37 / 3.08, over the minor 8.14 / 8.26 / 8.14, pill text 9.85 / 10.35 / 9.85, the cursor column 7.05 / 6.30 / 18.32 — PASS; greyscale: the crosshair by dash
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-196 MultiChartLinker (E11-D05, #310)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: non-visual (no frame to draw; the remote crosshair's frame is CMP-190's on board 02); page `E11-D05`
- [ ] N/A — **Variants × States matrix**: no visual variant or state (joined / left / modes changed are announcements, not frames); Table 1 carries one row for completeness
- [ ] N/A — **Keyboard table**: no interactive element of its own; the sync menu is CMP-218's (SCR-049)
- [x] **Accessible name / role table** — the shared polite status region announcing once ("Panes linked: crosshair, levels"); Table 3
- [x] **Live data** — the `sync` message ≤1 per frame; one announcement per state change, never per frame; Table 5
- [ ] N/A — **Motion pair**: none animated
- [ ] N/A — **Density notes**: no rendered geometry
- [x] **Essential-exceptions log** — none
- [ ] N/A — **Tokens used**: n/a (the `15` CMP-196 Tokens field reads n/a); Penpot token sets = `packages/ui/tokens` at `ced9a352b2785715ebe8ec74b3fd66443ed7ee05`
- [x] **Data contract confirmed** — `sync { groupId, timeRange, crosshair }` (`26` §6); time synced, price never (E11-D01)
- [ ] N/A — **Contrast and CVD**: no colour pair of its own (the remote crosshair is CMP-190's row 5.12 / 4.17 / 5.12)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-197 ChartTooltip (E11-D05, #310)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link — page + PNG** — page `E11-D05` · id `0bde4016-6d2e-8002-8008-d42e063e55da`; PNG at `docs/design/E11/img/E11-D05-06-primitives-matrix.png`
- [x] **Final Penpot link — ref frames** — the ref frames `CMP-197 · ChartTooltip — ref frame (<state>)` on board 10 `ref-frames-b` (id `c3fc69a9-a43c-8099-8008-df8e5122b161`, export `docs/design/E11/img/E11-D05-10-ref-frames-b.png`), page `E11-D05 ref frames` · id `cb0c3916-2579-81a4-8008-debf597b2f21` in the per-set file `E11-D05 ref frames` (spec §0 / §18; never the DS library file); the DS library entry routes to E11-T04 (#390)
- [x] **Variants × States matrix** — boards 01–08 drawn — spec §0; one ref frame per state on board 10 `ref-frames-b`, drawn 2026-10-30, spec §18; the full product is not drawn — the text is binding, RULED (orchestrator, #310 2026-10-30 12:09Z) Q2: 3 modes (follow / docked / off) × 6 states (E11-D02 D10; spec §8.6); Table 1
- [ ] N/A — **Keyboard table**: not focusable (`aria-hidden`; a pointer convenience); the keyboard path is the crosshair's (CMP-190) and the mirror's
- [x] **Accessible name / role table** — `aria-hidden="true"`; the mirror row and the live region carry the same values (E06-D03 D9); Table 3
- [x] **Live data** — repositioned and re-filled at most once per frame from the crosshair; never announced; Table 5
- [x] **Motion pair** — the fade in / out `motion.duration.fast` → instant under reduce (E11-D06); the flip is a position change, never animated; Table 4
- [x] **Density notes** — padding `space.inset.md` / `sm` / `xs`, value type `type.num.base` / `sm` / `xs`, width 200–260 px compact, ≤40 % of the pane; no target (not interactive); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.surface.overlay`, `color.border.default`, `radius.card`, `elevation.popover`, `color.text.secondary`, `color.text.primary`, `type.ui.caption` / `type.ui.label`, `type.num.*`, `space.inset.xs` / `space.inset.sm` / `space.inset.md`, `motion.duration.fast` = the `15` CMP-197 Tokens field; `elevation.3` and `font.mono` retired (spec G1); Penpot token sets = `packages/ui/tokens` at `ced9a352b2785715ebe8ec74b3fd66443ed7ee05`
- [x] **Data contract confirmed** — the bar store and the footprint cell under the cursor (`a11y` / `pick`); indicator rows through the E11-S07 field model
- [ ] **Contrast and CVD** — PENDING (PROPOSED `pairs.mjs` rows, spec CR-5; CVD run on the exports 2026-10-22, spec §10.3 — PASS): spec §10.1: title / values 13.27 / 14.37 / 15.02, labels 8.14 / 8.26 / 13.27 — PASS; the coloured numbers rejected (`color.candle.down` on the overlay 4.09 / 4.15 / 4.09); `color.text.buy` / `.sell` on the overlay 8.69 / 6.68 / 8.69 and 6.63 / 6.90 / 6.63 (CR-5, for E13's values)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-198 ChartWatermark / PaneBackground (E11-D05, #310)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link — page + PNG** — page `E11-D05` · id `0bde4016-6d2e-8002-8008-d42e063e55da`; PNG at `docs/design/E11/img/E11-D05-02-token-slots-three-themes.png`
- [x] **Final Penpot link — ref frames** — the ref frames `CMP-198 · ChartWatermark — ref frame (<state>)` on board 10 `ref-frames-b` (id `c3fc69a9-a43c-8099-8008-df8e5122b161`, export `docs/design/E11/img/E11-D05-10-ref-frames-b.png`), page `E11-D05 ref frames` · id `cb0c3916-2579-81a4-8008-debf597b2f21` in the per-set file `E11-D05 ref frames` (spec §0 / §18; never the DS library file); the DS library entry routes to E11-T04 (#390)
- [x] **Variants × States matrix** — boards 01–08 drawn — spec §0; one ref frame per state on board 10 `ref-frames-b`, drawn 2026-10-30, spec §18; the full product is not drawn — the text is binding, RULED (orchestrator, #310 2026-10-30 12:09Z) Q2: 1 variant × 4 states (E11-D02 D13; spec §8.7); Table 1
- [ ] N/A — **Keyboard table**: not interactive
- [x] **Accessible name / role table** — `aria-hidden` (decorative); the symbol and interval live in the toolbar and the canvas label; Table 3
- [ ] N/A — **Live data**: static chrome (the replay suffix changes with the session, not with data)
- [ ] N/A — **Motion pair**: none animated
- [x] **Density notes** — 48 / 48 / 40 px, hidden below 160 / 120 / 120 px of pane height; no target; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.chart.pane.bg.default`, `color.chart.pane.bg.focused`, `color.chart.watermark` (PROPOSED slots), `font.family.ui`, `font.weight.semibold` = the `15` CMP-198 Tokens field; Penpot token sets = `packages/ui/tokens` at `ced9a352b2785715ebe8ec74b3fd66443ed7ee05`
- [x] **Data contract confirmed** — symbol and interval from the chart config; the replay flag from the session
- [ ] **Contrast and CVD** — PENDING (the decorative slots need their documented exemption or class, spec Q4 / CR-5): spec §10.1: watermark 1.50 / 1.31 / 3.03 (decorative, `aria-hidden`), pane fill vs chrome rows 1.06 / 1.07 / 1.06 (a surface); nothing meaning-carrying; CVD n/a
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-199 ChartLegend (E11-D05, #310)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link — page + PNG** — page `E11-D05` · id `0bde4016-6d2e-8002-8008-d42e063e55da`; PNG at `docs/design/E11/img/E11-D05-06-primitives-matrix.png`
- [x] **Final Penpot link — ref frames** — the ref frames `CMP-199 · ChartLegend — ref frame (<state>)` on board 10 `ref-frames-b` (id `c3fc69a9-a43c-8099-8008-df8e5122b161`, export `docs/design/E11/img/E11-D05-10-ref-frames-b.png`), page `E11-D05 ref frames` · id `cb0c3916-2579-81a4-8008-debf597b2f21` in the per-set file `E11-D05 ref frames` (spec §0 / §18; never the DS library file); the DS library entry routes to E11-T04 (#390)
- [x] **Variants × States matrix** — boards 01–08 drawn — spec §0; one ref frame per state on board 10 `ref-frames-b`, drawn 2026-10-30, spec §18; the full product is not drawn — the text is binding, RULED (orchestrator, #310 2026-10-30 12:09Z) Q2: 3 densities × 8 states (E11-D02 D12; spec §8.8); Table 1
- [x] **Keyboard table** — one roving stop: `↑/↓` rows, `←/→` controls, `Space` / `Enter` toggle, `Enter` on "+N more" opens the popover (`Esc` closes, focus returns), `Esc` to the plot (E11-D02 §7.5); `Delete` reserved for E13; Table 2
- [x] **Accessible name / role table** — the eye toggle `aria-pressed` with the stable name "EMA 20 visible"; the row name carries "hidden"; the pane-label row's buttons named; Table 3
- [x] **Live data** — cursor values ≤1 per frame from the `a11y` / `viewport` message; toggles announce "EMA 20 hidden" / "shown" politely; Table 5
- [x] **Motion pair** — the popover opens instantly; visibility toggles never animate the series (E11-D06); Table 4
- [x] **Density notes** — rows 32 / 24 / 24 px, inset 12 / 8 / 4, the eye toggle 24 × 24 in every mode; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — inherits CMP-037; `type.ui.label` / `type.ui.body`, `type.num.*`, `color.text.primary`, `color.text.tertiary`, `color.action.primary.default`, `color.surface.overlay` + `elevation.popover`, `space.inset.xs` / `space.inset.sm` / `space.inset.md`, `size.control.compact` / `size.control.comfortable`, `color.focus.ring` = the `15` CMP-199 Tokens field; Penpot token sets = `packages/ui/tokens` at `ced9a352b2785715ebe8ec74b3fd66443ed7ee05`
- [x] **Data contract confirmed** — the bar under the cursor (`a11y` / `viewport`); the series list from `Pane.addSeries` / `addIndicator`
- [ ] **Contrast and CVD** — PENDING (PROPOSED `pairs.mjs` rows, spec CR-5; CVD run on the exports 2026-10-22, spec §10.3 — PASS): spec §10.1: label 15.20 / 16.78 / 17.21, value 9.33 / 9.65 / 15.20, hidden label 5.96 / 6.36 / 11.87, pane focus bar 3.85 / 4.44 / 7.05, the ring 7.05 / 6.30 / 18.32 — PASS; the shape swatch repeats the series kind (greyscale)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-226 BarCountdown (E11-D05, #310)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link — page + PNG** — page `E11-D05` · id `0bde4016-6d2e-8002-8008-d42e063e55da`; PNG at `docs/design/E11/img/E11-D05-06-primitives-matrix.png`
- [x] **Final Penpot link — ref frames** — the ref frames `CMP-226 · BarCountdown — ref frame (<state>)` on board 10 `ref-frames-b` (id `c3fc69a9-a43c-8099-8008-df8e5122b161`, export `docs/design/E11/img/E11-D05-10-ref-frames-b.png`), page `E11-D05 ref frames` · id `cb0c3916-2579-81a4-8008-debf597b2f21` in the per-set file `E11-D05 ref frames` (spec §0 / §18; never the DS library file); the DS library entry routes to E11-T04 (#390)
- [x] **Variants × States matrix** — boards 01–08 drawn — spec §0; one ref frame per state on board 10 `ref-frames-b`, drawn 2026-10-30, spec §18; the full product is not drawn — the text is binding, RULED (orchestrator, #310 2026-10-30 12:09Z) Q2: 2 densities × 4 states (E11-D02 D11; spec §8.9); Table 1
- [ ] N/A — **Keyboard table**: not interactive (text in the status row; the opt-in announcement is a Settings toggle)
- [x] **Accessible name / role table** — text with `aria-live="off"`; the opt-in 10 s announcement through the polite region; Table 3
- [x] **Live data** — 1 Hz, `aria-live="off"`; the opt-in announcement once at 10 s; Table 5
- [x] **Motion pair** — the warn flip is instant in both modes (E11-D06 D15); no per-second flash; Table 4
- [x] **Density notes** — row 32 / 24 px, pill 24 / 20 px, `type.num.sm` digits; no target; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `font.family.mono` via `type.num.sm`, `type.ui.caption`, `color.text.secondary`, `color.status.warning.subtle`, `color.text.primary`, `color.status.warning.strong`, `color.text.tertiary`, `font.weight.medium`, `color.surface.raised` = the `15` CMP-226 Tokens field; `font.mono`, `color.text.muted`, `color.status.warn` retired (spec G1); Penpot token sets = `packages/ui/tokens` at `ced9a352b2785715ebe8ec74b3fd66443ed7ee05`
- [x] **Data contract confirmed** — the WS-corrected server clock (E11-S07) and the bar interval; non-time bar types read `—` (E12-D06 D5 / E12-D09)
- [ ] **Contrast and CVD** — PENDING (PROPOSED `pairs.mjs` rows, spec CR-5; CVD run on the exports 2026-10-22, spec §10.3 — PASS): spec §10.1: normal 8.81 / 8.98 / 14.35, warn text 9.86 / 15.62 / 11.16, warn glyph 7.56 / 4.11 / 7.56, closed 5.62 / 5.92 / 11.21 — PASS; `warning.strong` as text rejected (4.11 in light); CVD: warn glyph vs normal text ≥53.6 under every deficiency
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

### Table 1 — Variants × States

| Component | Variant                    | State (every one is a Penpot ref frame and a story)                                                                            | Penpot ref frame (name pattern)                  | Story name(s)                                                                                                                                                                                                                         | Notes                                                     |
| --------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| CMP-180   | single pane / multi pane   | loading · streaming · stale · disconnected · replay · reduced detail · aggregated · context lost · recovering · empty          | `CMP-180 · ChartRoot — ref frame (<state>)`      | EmptyChart, SinglePane, MultiPane, ThemeSwitchDemo, DensityComfortable, DensityCompact, DensityDense, HighContrast, ReducedMotion, DegradedTwoD, ContextLostRecovery, SyncAnnouncement                                                | E11-D02 D16; `16` §10 item 4 (ref frames, not components) |
| CMP-188   | right gutter / left gutter | auto · locked · mode tag · last-price pill up · last-price pill down · mark pill · focused · dragging                          | `CMP-188 · PriceAxis — ref frame (<state>)`      | Linear, Log, Dragging (keyboard demo), Percent, Inverted, Locked, TwoGutters, LastPricePillUp, LastPricePillDown, MarkPill, HighContrast, Dense                                                                                       | E11-D02 D7                                                |
| CMP-189   | per density                | following · paused · boundary · maintenance band · loading band · go-to-date marker · remote crosshair · virtual-now · focused | `CMP-189 · TimeAxis — ref frame (<state>)`       | Default, ZoomedIn, ZoomedOut, Decimation0_5PxPerBar, Decimation3PxPerBar, Decimation12PxPerBar, Decimation50PxPerBar, SessionBoundary, MaintenanceBand, ClusterLive, ClusterPaused, LoadingBand, GoToDateMarker, Replay, HighContrast | E11-D02 D4 / D8                                           |
| CMP-190   | —                          | pointer · keyboard column · magnet snap · remote · coincident gridline · hidden during drag                                    | `CMP-190 · Crosshair — ref frame (<state>)`      | Default, SyncedAcrossPanes, KeyboardDriven, MagnetOn, RemoteCrosshair, CoincidentGridline, HiddenDuringDrag, KeyboardCursorColumn                                                                                                     | E11-D02 D3 / D9; E06-D03 D10                              |
| CMP-196   | —                          | joined · left · modes changed (announcements)                                                                                  | — (non-visual)                                   | covered: Crosshair/SyncedAcrossPanes, ChartRoot/MultiPane, ChartRoot/SyncAnnouncement                                                                                                                                                 | no frame                                                  |
| CMP-197   | follow / docked / off      | follow · flipped left · flipped above · clear of last price · docked · overflow                                                | `CMP-197 · ChartTooltip — ref frame (<state>)`   | OhlcvTooltip, FootprintCellTooltip, IndicatorTooltip, FlipLeft, FlipAbove, ClearOfLastPrice, Docked, OverflowTwelveRows, HighContrast                                                                                                 | E11-D02 D10                                               |
| CMP-198   | —                          | default · replay suffix · hidden below 120 px · dense 40 px                                                                    | `CMP-198 · ChartWatermark — ref frame (<state>)` | Default, HiddenBelow120px, Replay, Dense40px, FocusDoesNotChangeFill                                                                                                                                                                  | E11-D02 D13                                               |
| CMP-199   | per density                | default · one hidden · all hidden · overflow "+N more" · popover open · collapsed · pane-label row focused · estimated series  | `CMP-199 · ChartLegend — ref frame (<state>)`    | Default, ManyIndicators, AllHidden, PlusNMore, PopoverOpen, OneHidden, Collapsed, PaneLabelRowFocused, Comfortable, Compact, Dense                                                                                                    | E11-D02 D12                                               |
| CMP-226   | comfortable / compact      | normal · warn "closing" · closed · non-time `—`                                                                                | `CMP-226 · BarCountdown — ref frame (<state>)`   | Normal, Warning, Closed, NonTimeBar, Comfortable, HighContrast, ReducedMotionIdentical                                                                                                                                                | E11-D02 D11; `Atoms/BarCountdown` (spec G9)               |

### Table 2 — Keyboard

| Component                 | Key                                                                                                                | Action                                                                          | Focus after                                             | Global conflict?                                            | Notes                         |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------- | ----------------------------- |
| CMP-180                   | `Tab` / `Shift+Tab`; `Ctrl+\`                                                                                      | the chart region's stops in order; leave the region                             | the next stop / the next region                         | none (`05` §3.4 item 1)                                     | E11-D02 §12                   |
| CMP-180                   | `←/→`, `Shift+←/→` = `PageUp/PageDown`, `↑/↓`, `Home/End`, `Enter`                                                 | the plot cursor (bar, ±10 bars, level, edges, expand)                           | stays on the plot stop                                  | none (`05` §3.2 chart keys)                                 | E06-D03 D5 / D6               |
| CMP-188                   | `↑/↓`; `Shift+↑/↓`; `PageUp/PageDown`; `Home`; `Shift+F10`; `Esc`; `Tab`                                           | rescale 10 % / 25 %; pan 50 %; auto-fit; menu; back to the plot; the lock badge | the axis stop / the badge / the plot                    | none (axis-scoped; `Ctrl+drag` is E31's gesture, not a key) | E11-D02 §7.1                  |
| CMP-189                   | `←/→` (`Shift`); `+/−` (`Shift`); `Home`; `End`; `Ctrl+Home`; `Shift+F10`; `Esc`; cluster `←/→`, `Enter` / `Space` | pan; zoom; fit; latest; default spacing; menu; back; the cluster                | the strip stop / the cluster segment / the plot         | none (no modifier + wheel is bound, E11-D01)                | E11-D02 §7.2                  |
| CMP-190                   | as CMP-180's plot cursor                                                                                           | moves the crosshair (last input wins)                                           | the plot stop                                           | none                                                        | E11-D01 D4                    |
| CMP-199                   | `↑/↓`; `←/→`; `Space` / `Enter`; `Enter` on "+N more"; `Esc`                                                       | rows; controls; toggle; open the popover; back to the plot (popover: close)     | the row / the control / the "+N more" button / the plot | none (`Delete` reserved for E13)                            | E11-D02 §7.5                  |
| CMP-196 / 197 / 198 / 226 | —                                                                                                                  | not interactive                                                                 | —                                                       | —                                                           | N/A with reason in the blocks |

### Table 3 — Accessible name / role

| Component | Element                                             | Role                                                                   | Accessible name (source)                                                                                                     | States / properties                                                                              |
| --------- | --------------------------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| CMP-180   | the canvas                                          | `img`                                                                  | rolling label: symbol, interval, last, change (E06-D03 D4)                                                                   | throttled with the window; never per tick                                                        |
| CMP-180   | the root wrapper                                    | open: `application` (E06-D03 D4) or `img` + grid mirror (E11-D01 Q4-e) | symbol and interval only                                                                                                     | E11-D07 decides (spec Q8)                                                                        |
| CMP-180   | the DOM-mirror table                                | `table` (visually hidden, `clip-path`)                                 | "Bars" with `aria-rowcount` / `aria-rowindex`                                                                                | the cursor row `aria-current`; a cursor-centred window of 60 rows (cap 200)                      |
| CMP-180   | the two live regions                                | `status` (polite); `alert`                                             | pre-rendered, text content swapped only                                                                                      | ambient ≤1 per 2 s per field; discrete events never coalesced                                    |
| CMP-188   | the gutter surrogate                                | `group`                                                                | "Price axis, 63,900 to 64,300, linear, auto"                                                                                 | the range and mode in the name; the lock badge a `button` "Price scale locked"                   |
| CMP-189   | the strip surrogate; the cluster                    | `group`; three `button`s                                               | "UTC time axis, 14 Oct 07:30 to 13:47, 1 minute bars"; "Following live" / "Paused at 13:47 — resume live" / "Fit" / "Latest" | the `auto` button's name is its visible text (no `aria-pressed`); the zone tag `aria-live="off"` |
| CMP-190   | the focused bar's mirror row                        | `row`                                                                  | the bar summary (time, OHLCV, delta)                                                                                         | `aria-current="true"`; the pills are `aria-hidden` GL text                                       |
| CMP-196   | the shared status region                            | `status`                                                               | "Panes linked: crosshair, levels"                                                                                            | one announcement per change                                                                      |
| CMP-197   | the tooltip box                                     | none (`aria-hidden="true"`)                                            | —                                                                                                                            | the mirror and the live region carry the values                                                  |
| CMP-198   | the watermark                                       | none (`aria-hidden`)                                                   | —                                                                                                                            | decorative                                                                                       |
| CMP-199   | the legend; a series row; the eye toggle; "+N more" | `group`; `row`; `button` (`aria-pressed`); `button`                    | "Price pane legend"; "EMA 20, 64,003.2, hidden"; "EMA 20 visible" (stable); "6 more series"                                  | pressed = shown; the name never changes with state; the popover is a focus-managed roving group  |
| CMP-226   | the countdown text                                  | text (`aria-live="off"`)                                               | "bar close 0:41" / "0:08 closing" / "closed" / "—" with the title "No countdown for tick bars"                               | the opt-in 10 s announcement through the polite region                                           |

### Table 4 — Motion pair

| Component     | Property                               | motion-safe                                                                      | motion-reduce                        | Duration / easing tokens                                     |
| ------------- | -------------------------------------- | -------------------------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------ |
| CMP-180       | the stale dim (data-ink × 0.85)        | ramp 1.00 → 0.85 and back (E11-D06 D13)                                          | instant (the chip carries the state) | `motion.duration.normal`, `motion.easing.standard`           |
| CMP-180       | chips, badges, the replay frame        | state flips (E11-D06 D15)                                                        | identical                            | `motion.duration.instant`                                    |
| CMP-180       | the skeleton shimmer                   | 1,200 ms sweep (E11-D06 D16)                                                     | static two-tone                      | —                                                            |
| CMP-188       | a keyboard rescale                     | one frame (E11-D06 D11)                                                          | identical                            | `motion.duration.instant`                                    |
| CMP-189       | `fit` / `›` / go-to-date jumps         | ≤ `motion.duration.normal` (≤1 width), `slow` (≤3 widths), else cut (E11-D06 D7) | cut                                  | `motion.duration.normal` / `.slow`, `motion.easing.standard` |
| CMP-190       | the crosshair position; the leave fade | never eases; fade `motion.duration.fast` (E11-D06 D9)                            | never eases; instant                 | `motion.duration.fast`                                       |
| CMP-197       | the fade in / out                      | `motion.duration.fast`                                                           | instant                              | `motion.duration.fast`                                       |
| CMP-199       | the popover; a visibility toggle       | opens instantly; the series redraws instantly (E11-D06)                          | identical                            | `motion.duration.instant`                                    |
| CMP-226       | the warn flip                          | instant (E11-D06 D15)                                                            | identical                            | `motion.duration.instant`                                    |
| CMP-196 / 198 | none animated                          | —                                                                                | —                                    | —                                                            |

### Table 5 — Live data

| Component | Field                                         | Politeness                | Cadence                                                 | Coalescing          | Notes                            |
| --------- | --------------------------------------------- | ------------------------- | ------------------------------------------------------- | ------------------- | -------------------------------- |
| CMP-180   | the canvas label; the ambient region          | polite                    | ≤1 per 2 s per field (`05` §6.2)                        | latest value only   | E11-D02 §10; never per tick      |
| CMP-180   | context lost / restored, stale, LOD step-down | `role="alert"`            | once per event                                          | never coalesced     | E11-D02 §10                      |
| CMP-188   | the last-price pill and line                  | none (visual)             | per tick, colour held ≤2/s                              | the bar's direction | no flash (ORCH-1)                |
| CMP-189   | the zone tag's clock; "Paused at hh:mm"       | off; polite once          | 1 Hz; on pausing                                        | —                   | E11-D02 D8                       |
| CMP-190   | the cursor announcement                       | polite                    | lead 0 ms, repeat window 500 ms, trailing flush ≤250 ms | latest state        | E06-D03 D5; pointer moves silent |
| CMP-196   | sync-state change                             | polite                    | once per change                                         | —                   | E11-S09                          |
| CMP-197   | the readout values                            | none (`aria-hidden`)      | ≤1 reposition per frame                                 | per frame           | the mirror carries the values    |
| CMP-199   | cursor values; toggle announcements           | none; polite              | ≤1 per frame; per toggle                                | latest bar          | E11-D02 D12                      |
| CMP-226   | the countdown                                 | off (opt-in once at 10 s) | 1 Hz                                                    | —                   | E11-D02 D11                      |
| CMP-198   | —                                             | —                         | static                                                  | —                   | N/A                              |

### Density

| Component         | Mode                  | Row / control height                                                                                                                                                     | Padding tokens                                | Smallest target                      |
| ----------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------- | ------------------------------------ |
| CMP-180           | comfortable           | rows 32 px (`size.control.comfortable`); `cellPadPx` 4                                                                                                                   | `space.inset.md` (12); spacing step `space.3` | 24 × 24 px (`size.target.min`)       |
| CMP-180           | compact               | rows 24 px (`size.control.compact`); `cellPadPx` 2                                                                                                                       | `space.inset.sm` (8); `space.2`               | 24 × 24 px                           |
| CMP-180           | dense                 | rows 24 px (the DOM chrome keeps compact's rows, targets and type; insets take the third value, read from CMP-180's `density` prop, never `data-density`); `cellPadPx` 1 | `space.inset.xs` (4); `space.1`               | 24 × 24 px (D6 rule 3)               |
| CMP-188 / CMP-189 | comfortable           | gutter padding 8; strip 32 px; `type.num.base` 13 px                                                                                                                     | `space.2`; `G` 48 / 96 px                     | the gutter ≥48 px wide; strip 32 px  |
| CMP-188 / CMP-189 | compact               | gutter padding 4; strip 24 px; `type.num.sm` 11 px                                                                                                                       | `space.1`; `G` 40 / 80 px                     | 24 px                                |
| CMP-188 / CMP-189 | dense                 | gutter padding 4; strip 24 px; `type.num.xs` 10 px                                                                                                                       | `space.1`; `G` 32 / 64 px                     | 24 px (floor)                        |
| CMP-190           | all                   | pill 20 / 17 / 16 px; cursor column ≥2 px                                                                                                                                | `type.num.*` per density                      | the plot stop                        |
| CMP-197           | all                   | padding `space.inset.md` / `sm` / `xs`; width 200–260 px                                                                                                                 | `type.num.base` / `sm` / `xs`                 | not interactive                      |
| CMP-198           | all                   | 48 / 48 / 40 px; hidden below 160 / 120 / 120 px                                                                                                                         | —                                             | not interactive                      |
| CMP-199           | all                   | rows 32 / 24 / 24 px; inset 12 / 8 / 4                                                                                                                                   | `space.inset.md` / `sm` / `xs`                | the eye toggle 24 × 24 in every mode |
| CMP-226           | comfortable / compact | row 32 / 24 px; pill 24 / 20 px                                                                                                                                          | `space.inset.md` / `sm`                       | not interactive                      |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all nine  | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12) — the nine primitives

- [x] Only published Tier-2 tokens or the PROPOSED `color.chart.*` slots of spec §4 — zero hard-coded hex / px in the spec (the tool resolves every value).
- [ ] Verified in all three themes at both density modes — PENDING: the ref frames (boards 09 / 10 on page `E11-D05 ref frames` · id `cb0c3916-2579-81a4-8008-debf597b2f21`, drawn 2026-10-30 in dark only, spec §18; boards 01–08 are drawn on page `E11-D05` · id `0bde4016-6d2e-8002-8008-d42e063e55da`) and the built surfaces (E11-D08's 9-cell matrix); the matrix of spec §10.1 covers the tokens in all three themes.
- [x] Passes the contrast matrix for every pair it introduces or touches — 68 gated rows, 0 FAIL (the token PR registers the PROPOSED pairs).
- [x] CVD simulation reviewed for any new colour-carrying state — the ΔE76 rows of spec §10.3 computed; `cvd_sim.py` run on the eight exports of page `E11-D05` · id `0bde4016-6d2e-8002-8008-d42e063e55da` on 2026-10-22 (spec §10.3, the per-board table): no new colour-only state; PASS on the four boards that draw a colour-carried state, whose renders are committed — `docs/design/E11/img/E11-D05-02-token-slots-three-themes-greyscale.png`, `docs/design/E11/img/E11-D05-02-token-slots-three-themes-deuteranopia.png`, `docs/design/E11/img/E11-D05-03-ramps-oklab-greyscale.png`, `docs/design/E11/img/E11-D05-03-ramps-oklab-deuteranopia.png`, `docs/design/E11/img/E11-D05-05-pattern-registry-greyscale.png`, `docs/design/E11/img/E11-D05-05-pattern-registry-deuteranopia.png`, `docs/design/E11/img/E11-D05-06-primitives-matrix-greyscale.png`, `docs/design/E11/img/E11-D05-06-primitives-matrix-deuteranopia.png`; boards 01, 04, 07 and 08 checked, no colour-carried state (nothing committed); the tool simulates deuteranopia only — protanopia and tritanopia are covered per pair by the same non-colour channels (spec §10.3, limits).
- [ ] Every documented State has a Penpot variant and a Storybook story — PENDING (one ref frame per state on boards 09 / 10, drawn 2026-10-30, spec §18 — the full products are not drawn, the text is binding; 79 stories specified, none built — E11-S06 / E11-T08).
- [x] Disabled states use disabled-with-reason — N/A (no RBAC / env-gated action in the nine primitives).
- [x] Loading / empty / error states explicitly designed — E11-D02 D16 (cited); SCR-047 / SCR-048 are E11-D04's.
- [x] Keyboard-interaction table completed — Table 2 (E11-D02 §7 / §12 tables).
- [x] Accessible-name / role table completed — Table 3.
- [x] For canvas / WebGL-adjacent components the DOM-mirror / windowed-tree strategy is specified — `05` §6.1, E06-D03 D1–D10, E11-D02 §12 (cited in every entry's A11y field).
- [x] Motion-safe / motion-reduce pair specified for any animated property — Table 4 (E11-D06 D-ids).
- [x] Hit targets meet 24 px (compact) / 40–44 px (comfortable) or an essential exception is logged — 24 px floors in every chart density; none logged.
- [ ] Accessibility role has signed off — owner approval pending.
- [x] Confirm-gate variants — N/A (no order placement in the nine primitives; `Ctrl+drag` is E31's).
- [x] Heuristic / estimated values chip-tagged — the registry (spec §7) and CMP-227 (cited); the legend's estimated row carries "(estimated)".
- [x] Demo / Live env context — the env badge is CMP-075's, not these primitives'.
- [x] Reuses an existing CMP-\* rather than a near-duplicate — no new id (the count stays 239).
- [x] Storybook stories match the Variants × States matrix — Table 1.
- [ ] Composes only published-library components — the ref frames are specimens on the ticket's own per-set page `E11-D05 ref frames` (`16` §10 item 4), not library components; N/A by construction for chart primitives.

## B. Accessibility acceptance criteria (`05` §10) — the nine primitives

```gherkin
Feature: Chart primitives (CMP-180, 188, 189, 190, 196, 197, 198, 199, 226) — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user pans, zooms, rescales an axis, moves the crosshair, toggles a legend row and resizes a pane
    Then every control involved is reachable via Tab/arrow-key navigation (E11-D02 §12 order)
    And every drag (axis rescale, time pan, splitter) has the documented key equivalent (Table 2)
    And focus is never silently moved by a background data update
    And the CMP-039 ring (2 px, 2 px offset, 1 px pane-colour halo) is visible at every step, ≥6.30:1

  Scenario: Screen-reader operation
    Given the user is using NVDA or VoiceOver with the keyboard
    When the user moves the data cursor and reads the axes and the legend
    Then the surrogate groups, the mirror rows and the eye toggles are announced with their names (Table 3)
    And ambient values follow the polite ≤1 per 2 s cadence and the cursor the E06-D03 D5 cadence
    And the DOM mirror holds parity with the canvas at every LOD tier and render profile

  Scenario: Colour-independence
    Given the chart displays direction, estimated data, a gap, imbalance or a degraded state
    When the state is rendered
    Then it is also conveyed by glyph, dash, hatch, outline or text (spec §7 registry; §10.3)
    And the ramps and the series pair pass deuteranopia / protanopia / tritanopia simulation review (spec §5.4, §10.3)

  Scenario: Contrast
    Given the chart is rendered in the dark theme and the high-contrast theme
    Then all engine text meets ≥4.5:1 (axis labels 5.96 / 11.87) and all meaning-carrying lines ≥3:1 (spec §10.1)
    And decorative gridlines and the watermark are below 3:1 by design and carry no meaning

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override)
    When the chart would dim, fade, jump or shimmer
    Then it uses the motion-reduce variant of Table 4 with no flashing content

  Scenario: Automated gates
    Given a chart-primitive story is opened
    Then axe reports zero new serious/critical violations over the mirror and the chrome
    And the DOM-mirror parity test and the performance-budget test pass (spec §9.2)
```

Screen-reader spot-testing is deferred to E11-D07's review and the release-level pass (`05` §8) — stated, not assumed. No owner-approved exception exists.
