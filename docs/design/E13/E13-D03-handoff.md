# E13-D03 — Per-component handoff checklist (`16` §11.4)

Five blocks (one per component contract this ticket changes — CMP-194 IndicatorOverlay, CMP-195 AnnotationMarker, CMP-197 ChartTooltip, CMP-199 ChartLegend, CMP-224 IndicatorChips; every line of the `16` §11.4 block kept), then Tables 1–5, the Density table and the Essential-exceptions table **once each with a leading `Component` column** so every component's rows are present without five copies (the E11-D05 / E25-D05 shape; deviation recorded in `E13-D03.md` §21; the fallback is per-component tables). The Penpot line follows the page-ref rule (page **name + id**; never a hostname, team or file id, or a workspace URL) and reads BLOCKED-PENPOT until hpe-worker-1 draws the fifteen boards of `E13-D03.md` §0. Spec: `docs/design/E13/E13-D03.md`; tokens: `packages/ui/tokens` at `216b0b3859acb8dbd93ca65decf7ef62963469fc` (byte-identical at the base `3f736b313abe6734d01cf410528ee985043e0d0b`); matrix and alpha: `docs/design/_tools/e13_d03_palette_audit.py` (105 pairs × 3 themes, 57 gated, FAIL 0; `opacity.indicator.fill` 0.20, the worst candle ratio 3.26:1 under the candles and 3.04:1 over them). The pre-PR design-review lens round 1 (2026-10-22), the standing T2 gate pre-check T2-precheck-4212 (2026-10-23), hpe-worker-1's T2 self-check T2-recheck-4212 (2026-10-23) , the orchestrator's first text round (2026-10-23: SCR-036's eye and lock by row kind, the slot-vs-slot ΔE floor, the lane-wide form-validity look) and the orchestrator's fold confirm (2026-10-23: the #314 rulings of record, issuecomment-6356062207 — Q-6 RULED, the hue-first assignment stays the default, C-26 RULED, the per-instance ladder tier the PROPOSED E47-D05 user preference "Distinguish series by line style"; the stale figures; the public cites) are folded.

## Handoff checklist — CMP-194 IndicatorOverlay (E13-D03, #314)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E13-D03 Indicator hi-fi and visual language` (created by name on the board script's first run; id pinned here once it exists); planned PNGs `docs/design/E13/img/E13-D03-10-series-lines-ladder.png`, `E13-D03-11-series-bands-histograms-markers.png`, `E13-D03-13-ten-indicator-stress.png`; the DS library entry is E13-D04 / E13-D06's
- [ ] **Variants × States matrix** — PENDING the boards: 8 slots × 6 line tiers, 3 bar tiers, 3 band tiers (spec §3, §4) × the states normal / hidden / computing / insufficient history / before-history / errored / provisional / stale / rebuilding (spec §7.1); Table 1
- [ ] N/A — **Keyboard table**: the overlay is not focusable; its values are read through the legend row (CMP-199), the DOM mirror and the keyboard cursor (E06-D03 D5 / D10); Table 2 carries the legend's keys
- [x] **Accessible name / role table** — a series has no DOM node of its own; its name is the legend row's ("EMA 21") and its value the mirror's; Table 3
- [x] **Live data** — the series redraws at the chart's cadence and is never announced; the legend values update visually only — events per E13-D02 §11.4 (once, polite) — and the stale / rebuilding rows carry their words (spec §7.1); Table 5
- [x] **Motion pair** — none animated by this spec: a theme switch is a LUT re-upload (`26` §5 rule 1), the add / remove and sub-pane transitions are E13-D04's, instant under reduce (E13-D02 §11.6); Table 4
- [x] **Density notes** — the series geometry is in CSS px, device-snapped (E11-D02 §4.4) and independent of density; the legend row it drives is 32 / 24 / 24 px (E11-D02 D6); the smallest target is the legend eye 24 × 24; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.indicator.palette.1` … `.8`, `opacity.indicator.fill`, `size.stroke.thin` / `.regular` / `.bold` (PROPOSED, spec §10.5 CR-1 / CR-2), `color.candle.up` / `color.candle.down` (Volume's up / down), `color.text.tertiary` (guide levels, zero lines), `color.surface.canvas`; the dash ids `dash.solid` / `dash.8-4` / `dash.8-3-2-3` and the bar ids `bar.full` / `bar.narrow` / `bar.outline` (CR-3); none invented; Penpot token sets = `packages/ui/tokens` at `216b0b3859acb8dbd93ca65decf7ef62963469fc`
- [x] **Data contract confirmed** — `GET /api/v1/indicators` (`IndicatorDescriptor.outputs[]` in kernel order, `pane`, `compute`, `warmup_bars`, `nullable_when`), the WS `indicators.{symbol}.{bar_type}.{param}` topic (`23` §6.1 / §14.10: `null` before warmup, `meta.stale`), `GET /api/v1/indicator-presets` (`style` — the closed vocabulary, spec §9, G-1); the per-output `kind` / `fill_to` / `levels[]` is E13-D02 CG-7 (spec G-2)
- [ ] **Contrast and CVD** — PENDING the token PR's `pairs.mjs` rows (spec §10.5 CR-5) and the `cvd_sim.py` run on the exports: spec §10.1 — every slot ≥ 3:1 on the canvas in all three themes (lowest 3.05, slot 4 dark), ≥ 8 ΔE from every semantic colour token except the surface tiers (106 per theme) and from every other slot (all 28 pairs gated; the smallest 14.2), and ≥ 5 ΔE under protanopia / deuteranopia but for the four recorded residuals (C-28); 84 slot-pair CVD rows, 4 tritanopia-only collapses carried by the tier; the band fill at 0.20 keeps the worst candle ratio at 3.26:1 under the candles, 3.04:1 over them and 3.50:1 in the CVD-safe palette, fills never compounding (spec §10.4); the greyscale residual recorded and AC 1 marked not met as RULED for unrelated same-tier series (spec §10.3; C-26 and Q-6 RULED on #314, issuecomment-6356062207: the hue-first assignment stays the default, the per-instance ladder tier is E47-D05's PROPOSED preference "Distinguish series by line style")
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — CMP-195 AnnotationMarker (E13-D03, #314)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E13-D03 Indicator hi-fi and visual language`; planned PNGs `docs/design/E13/img/E13-D03-11-series-bands-histograms-markers.png`, `E13-D03-12-sub-panes-guides-collapse.png`
- [ ] **Variants × States matrix** — PENDING the boards: glyphs ◆ / ● / ■ (identity), ▲ / ▼ (direction, with a word), `icon/divergence` (with a word), the provisional pivot (dashed outline + "provisional") × confirmed / provisional / hidden (spec §4.4); Table 1
- [ ] N/A — **Keyboard table**: markers are informational and not focusable; the keyboard cursor reaches a marker bar like any bar and the mirror row reads the marker's word (E06-D03 D4 / D10; spec §12)
- [x] **Accessible name / role table** — no DOM node of its own; the mirror row's sentence carries the word ("Supertrend flip up", "Bullish divergence", "swing high 63,980 provisional"); Table 3
- [x] **Live data** — a marker appears on bar close; never announced per marker (the ambient region is unaffected); Table 5
- [x] **Motion pair** — none animated: markers appear as state flips (E11-D06 D15); Table 4
- [x] **Density notes** — glyph ≤ 12 px in every density (one L0 footprint row), labels DOM in `type.ui.caption` that yield when closer than their width, ≤ 24 per pane (spec §4.4); an interactive marker's target padded to ≥ 24 px; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — the instance's slot `color.indicator.palette.n` (PROPOSED), `color.text.primary` (the DOM label), `color.surface.canvas` (the label's halo); the glyph ids `glyph.diamond` / `glyph.disc` / `glyph.square`, `icon/divergence` and `pattern.dashed.provisional` for the provisional pivot and leg (PROPOSED, spec §10.5 CR-3 / CR-7); `color.marker.*` does not exist (spec C-20); Penpot token sets = `packages/ui/tokens` at `216b0b3859acb8dbd93ca65decf7ef62963469fc`
- [x] **Data contract confirmed** — Supertrend `direction` (+1 / −1) and Zig Zag `swing_high` / `swing_low` from the `indicators.*` series; the provisional leg is never published (`24` §7.4; E13-X01 §5 item 4); divergence events are the detector's (E13-S03's scope), drawn by reference
- [ ] **Contrast and CVD** — PENDING as CMP-194: the glyph takes the slot's measured ratios (spec §10.1: slots on the canvas); direction and divergence carry words, so no CVD pair is relied on
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-197 ChartTooltip (E13-D03, #314)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E13-D03 Indicator hi-fi and visual language`; planned PNG `docs/design/E13/img/E13-D03-08-states-legend-chip.png`
- [ ] **Variants × States matrix** — PENDING the boards: the indicator rows (one series / multi-output / ribbon) × follow / docked / overflow (E11-D02 D10; spec §7.4); Table 1
- [ ] N/A — **Keyboard table**: not focusable (`aria-hidden`; a pointer convenience); the keyboard path is the crosshair's and the mirror's (E11-D05 CMP-197 block, cited)
- [x] **Accessible name / role table** — `aria-hidden="true"`; the mirror row and the cursor's live region carry the same values (E06-D03 D9); Table 3
- [x] **Live data** — re-filled at most once per frame from the crosshair; never announced; Table 5
- [x] **Motion pair** — the fade `motion.duration.fast` → instant under reduce (E11-D06; unchanged); Table 4
- [x] **Density notes** — padding `space.inset.md` / `space.inset.sm` / `space.inset.xs`, values `type.num.base` / `type.num.sm` / `type.num.xs` per density (E11-D05); not interactive; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.surface.overlay`, `color.border.default`, `radius.card`, `elevation.popover`, `color.text.secondary`, `color.text.primary`, `type.num.*`, `type.ui.caption`, the slot hue on a 16 × 10 `color.surface.canvas` tile for the row swatch (PROPOSED); `font.mono` retired for `font.family.mono` (spec C-21); Penpot token sets = `packages/ui/tokens` at `216b0b3859acb8dbd93ca65decf7ef62963469fc`
- [x] **Data contract confirmed** — the crosshair's bar and the `indicators.*` points at it; `IndicatorOutput.name` labels a multi-output row
- [ ] **Contrast and CVD** — PENDING as CMP-194: `color.text.primary` / `.secondary` on the overlay 13.27 / 14.37 / 15.02 and 8.14 / 8.26 / 13.27; the slot on its canvas tile ≥ 3.05 (spec §10.1; the overlay around the tile is reported)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-199 ChartLegend (E13-D03, #314)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E13-D03 Indicator hi-fi and visual language`; planned PNGs `docs/design/E13/img/E13-D03-08-states-legend-chip.png`, `E13-D03-13-ten-indicator-stress.png`, `E13-D03-14-hc-densities-matrix.png`
- [ ] **Variants × States matrix** — PENDING the boards: per density (32 / 24 / 24) × the twelve row states of spec §7.1 × the multi-output / ribbon / "+N more" forms (E13-D02 D27 / D28); Table 1
- [x] **Keyboard table** — E11-D02 D12 / E13-D02 §11 unchanged: one roving stop before the plot; `↑/↓` rows, `←/→` a row's controls, `Space` toggles visibility, `Enter` on the value opens the quick-edit (E13-D02 C-12, proposed), `Enter` on "+N more" opens the popover, `Esc` back to the plot; no global binding touched; Table 2
- [x] **Accessible name / role table** — the row's name (label + params, with "hidden" / "stale" / "used by rules" / "provisional" as words); the eye's stable name "EMA 21 visible" (`aria-pressed`); the "+N more" button "6 more series" (`aria-expanded`); the quick-edit field "Period for EMA 21" (`spinbutton`); Table 3
- [x] **Live data** — the value updates visually only — never announced, as E13-D02 §11.4 decided (Table 5); the stale row freezes its value ("Stale 7s"), the rebuilding row keeps it; events per E13-D02 §11.4: once, polite, one line per add / hide / rebuild batch; Table 5
- [x] **Motion pair** — "state flips instant in both modes (E11-D06 D15); the add / remove and sub-pane transitions are E13-D04's"; the popover `fast` fade → instant; Table 4
- [x] **Density notes** — rows 32 / 24 / 24 (comfortable / compact / dense), the 8 × 8 swatch and the 24 × 24 eye in every mode, `type.ui.label` / `type.ui.caption` labels, `type.num.sm` / `type.num.xs` values; the smallest target 24 × 24; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — inherits CMP-037; `color.indicator.palette.n` for the swatch (PROPOSED), `color.text.primary`, `color.text.secondary`, `color.text.tertiary` (hidden, stale), `color.status.danger.strong` / `color.status.warning.strong` (the error / rule glyph), `color.surface.canvas`, `color.surface.hover`, `color.surface.overlay` + `elevation.popover` (the popover), `color.text.link` ("Manage all…"), `color.focus.ring`, `type.num.*`, `type.ui.label`, `type.ui.caption`, `space.inset.sm` / `space.inset.xs`, `size.control.height`; none invented; Penpot token sets = `packages/ui/tokens` at `216b0b3859acb8dbd93ca65decf7ef62963469fc`
- [x] **Data contract confirmed** — `indicators.{symbol}.{bar_type}.{param}` points (`null` before warmup; `meta.stale`; `generation_swap` / `history_repair` snaps replace the series whole — `23` §7.4), `IndicatorDescriptor.warmup_bars` / `nullable_when`, the chart's instance list; the referencing count (used by rules) is E13-D02 CG-2's
- [ ] **Contrast and CVD** — PENDING the token PR's rows and the export run: spec §10.1 — label 15.20 / 16.78 / 17.21, value 9.33 / 9.65 / 15.20, hidden 5.96 / 6.36 / 11.87, the error glyph 9.87 / 4.41 / 9.87, the rule glyph 11.65 / 4.41 / 11.65, the ring 7.05 / 6.30 / 18.32; the swatch takes the slot's ratios
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-224 IndicatorChips (E13-D03, #314)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E13-D03 Indicator hi-fi and visual language`; planned PNGs `docs/design/E13/img/E13-D03-05-manager-dark.png`, `E13-D03-08-states-legend-chip.png`, `E13-D03-14-hc-densities-matrix.png`
- [ ] **Variants × States matrix** — PENDING the boards: the count chip (E11-D02 A-14, E13-D02 D29) × `Ind 0` / `Ind 4` / `· 1 hidden` / `· 1 error` / `· 2 stale` / `· 1 computing` / `Ind 10` / `Ind 20` × compact / comfortable × three themes (spec §7.3); Table 1
- [x] **Keyboard table** — a button on the toolbar's roving stop (E11-D02 D18): `Enter` / `Space` opens SCR-036 for this chart; `Esc` from the drawer returns focus to the chip; no global conflict (not in `05` §3.2); Table 2
- [x] **Accessible name / role table** — `button`, name "Indicators: 4 on this chart, 1 hidden — open the object manager" (E13-D02 §11.3); Table 3
- [x] **Live data** — the count and the one suffix change per state change, never per tick; no live region of its own (the legend rows and the connection chip announce); Table 5
- [x] **Motion pair** — a state flip, instant in both modes (E11-D06 D15); Table 4
- [x] **Density notes** — a 20 px pill in a 24 px hit box (compact) / a 24 px pill (comfortable), `type.ui.caption`; the smallest target 24 × 24 (E11-D02 §12); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.surface.raised`, `color.text.tertiary` (the 1 px border), `color.text.primary` (the words), `color.status.danger.strong` / `color.status.warning.strong` / `color.status.info.strong` / `color.text.tertiary` (the suffix glyph: error / stale / computing / hidden), `radius.pill`, `type.ui.caption` (`font.size.xs`), `color.focus.ring`; none invented; Penpot token sets = `packages/ui/tokens` at `216b0b3859acb8dbd93ca65decf7ef62963469fc`
- [x] **Data contract confirmed** — the chart's instance list and each row's state (spec §7.1); the suffix order error → stale → computing → hidden (E13-D02 D29)
- [ ] **Contrast and CVD** — PENDING the token PR's rows: spec §10.1 — the words 14.35 / 15.62 / 16.25 on raised, the error glyph 9.32 / 4.11 / 9.32, the ring 6.66 / 5.86 / 17.30; the hue rides on the glyph only, so no CVD pair is relied on
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

### Table 1 — Variants × States

| Component | Variant                                                | State (every one a Penpot frame on the boards of spec §0 and a story)                                                                      | Penpot frame (board)                     | Story name(s)                                                                                                                                                               |
| --------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-194   | 8 slots × 6 line tiers; 3 bar tiers; 3 band tiers      | normal · hidden · computing · insufficient history (warm-up hatch) · before-history · errored · provisional (Zig Zag) · stale · rebuilding | 10 `SCR-030 series-lines-ladder`, 11, 13 | SingleLine, WithBands, Dashed (catalogue) + Tiers, BandFillAlpha, Histogram, Provisional, HighContrast                                                                      |
| CMP-195   | ◆ / ● / ■ identity; ▲ / ▼ direction; `icon/divergence` | confirmed · provisional (dashed outline + word) · hidden with its series                                                                   | 11, 12                                   | IconMarker, ShapeMarker (catalogue) + SupertrendFlip, ZigZagPivot, Divergence, Provisional                                                                                  |
| CMP-197   | follow / docked / off (E11-D02 D10)                    | one series row · multi-output rows · ribbon rows · overflow "+3 more · Alt+T"                                                              | 08 `SCR-036-030 states-legend-chip`      | IndicatorTooltip (catalogue) + MultiOutput, Overflow                                                                                                                        |
| CMP-199   | per density (32 / 24 / 24)                             | the twelve states of spec §7.1 · multi-output · ribbon collapsed / expanded · "+N more" · popover open · pane-label row focused            | 08, 13, 14                               | Default, ManyIndicators, AllHidden (catalogue) + Errored, WarmingUp, BeforeHistory, MultiOutput, Ribbon, UsedByRules, Provisional, Stale, Rebuilding, Editing (E13-D02 A-4) |
| CMP-224   | compact / comfortable; three themes                    | `Ind 0` · `Ind 4` · `Ind 4 · 1 hidden` · `Ind 4 · 1 error` · `Ind 4 · 2 stale` · `Ind 4 · 1 computing` · `Ind 10` · `Ind 20` · focused     | 05, 08, 13, 14                           | None, Several, WithHidden, WithError, WithComputing (E13-D02 A-3)                                                                                                           |

### Table 2 — Keyboard

| Component | Key                     | Action                                                                   | Focus after          | Global conflict?                               | Notes                                 |
| --------- | ----------------------- | ------------------------------------------------------------------------ | -------------------- | ---------------------------------------------- | ------------------------------------- |
| CMP-199   | `Tab` (into the legend) | the legend row that last had focus (one roving stop before the plot)     | the row              | none                                           | E11-D02 D12, D18                      |
| CMP-199   | `↑` / `↓`               | previous / next row                                                      | the row              | none                                           | wraps never; the price row is row 1   |
| CMP-199   | `←` / `→`               | the row's controls (value, eye, menu); on a ribbon row collapse / expand | the control          | none                                           | E13-D02 D28                           |
| CMP-199   | `Space`                 | toggle visibility ("EMA 21 hidden" / "shown")                            | stays                | none (`Space` is visibility everywhere in E13) | E13-D02 C-6 / C-12                    |
| CMP-199   | `Enter` (on the value)  | open the quick-edit (or the D17 guard for a referenced instance)         | the field            | none                                           | E13-D01 AD-3; E13-D02 C-12 (proposed) |
| CMP-199   | `Enter` (on "+N more")  | open the popover                                                         | the first hidden row | none                                           | `Esc` returns to the button           |
| CMP-199   | `Esc`                   | back to the plot cursor                                                  | the plot             | reserved key, untouched                        | `05` §3.3                             |
| CMP-224   | `Enter` / `Space`       | open SCR-036 for this chart                                              | the first tree item  | none                                           | `Esc` from the drawer returns here    |
| CMP-194   | — (not focusable)       | values through the legend row, the mirror and the keyboard cursor        | —                    | —                                              | E06-D03 D5 / D10                      |
| CMP-195   | — (not focusable)       | the mirror row at a marker bar reads the marker's word                   | —                    | —                                              | spec §12                              |
| CMP-197   | — (`aria-hidden`)       | the crosshair's keys are CMP-190's                                       | —                    | —                                              | E11-D05's CMP-197 block               |

### Table 3 — Accessible name / role

| Component | Element                | Role                  | Accessible name (source)                                                                                 | States / properties                                                 |
| --------- | ---------------------- | --------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| CMP-199   | the row                | `group` (roving item) | "EMA 21", with "hidden" / "stale" / "used by rules" / "provisional" appended as words (E13-D02 D27)      | `aria-current` on the focused row                                   |
| CMP-199   | the eye                | `button`              | "EMA 21 visible" — stable (E11-D02 D12)                                                                  | `aria-pressed`                                                      |
| CMP-199   | the value (quick-edit) | `spinbutton`          | "Period for EMA 21" (label "primary parameter (per descriptor)", E13-D02 OQ-B)                           | `aria-valuenow` / `min` / `max`; `aria-invalid` on a rejected value |
| CMP-199   | "+N more"              | `button`              | "6 more series"                                                                                          | `aria-expanded`                                                     |
| CMP-224   | the chip               | `button`              | "Indicators: 4 on this chart, 1 hidden — open the object manager" (E13-D02 §11.3)                        | —                                                                   |
| CMP-194   | a series               | — (canvas)            | named by its legend row; valued by the mirror row at the cursor bar (E06-D03 D4)                         | —                                                                   |
| CMP-195   | a marker               | — (canvas)            | the mirror row's sentence: "Supertrend flip up" / "Bullish divergence" / "swing high 63,980 provisional" | —                                                                   |
| CMP-197   | the tooltip            | `aria-hidden`         | — (the mirror and the cursor's live region carry the values, E06-D03 D9)                                 | —                                                                   |

### Table 4 — Motion pair

| Component | Property                                | motion-safe                                     | motion-reduce | Duration / easing tokens  |
| --------- | --------------------------------------- | ----------------------------------------------- | ------------- | ------------------------- |
| CMP-199   | row add / remove, the sub-pane collapse | E13-D04's (not specified here)                  | instant       | E13-D04                   |
| CMP-199   | state words, the swatch, the eye        | state flips (E11-D06 D15)                       | identical     | `motion.duration.instant` |
| CMP-199   | the "+N more" popover                   | `fast` fade (E11-D02 D12)                       | instant       | `motion.duration.fast`    |
| CMP-224   | the count and the suffix                | state flip (E11-D06 D15)                        | identical     | `motion.duration.instant` |
| CMP-197   | appear / leave                          | `fast` fade (E11-D06)                           | instant       | `motion.duration.fast`    |
| CMP-194   | a theme switch                          | a LUT re-upload, no transition (`26` §5 rule 1) | identical     | none                      |
| CMP-195   | a marker's appearance on bar close      | a state flip                                    | identical     | `motion.duration.instant` |

### Table 5 — Live data

| Component | Field                                                           | Politeness    | Cadence                                                 | Coalescing        | Notes                                           |
| --------- | --------------------------------------------------------------- | ------------- | ------------------------------------------------------- | ----------------- | ----------------------------------------------- |
| CMP-199   | the cursor value                                                | none (visual) | the chart's cadence                                     | latest value      | never announced per tick (E13-D02 §11.4)        |
| CMP-199   | add / hidden / shown / needs N bars / error / rebuilt / applied | polite        | once per event; one line per chart per swap batch       | the rebuilt batch | E13-D02 §11.4 verbatim                          |
| CMP-199   | stale                                                           | none          | the row freezes; the connection chip announces          | —                 | `23` §7.2 `meta.stale`                          |
| CMP-224   | the count and the suffix                                        | none          | per state change                                        | —                 | the legend rows announce                        |
| CMP-194   | the series                                                      | none          | the chart's cadence; the visible window first (D6, D13) | —                 | `06` §4.3 ≤ 2 ms, every second frame under load |
| CMP-195   | markers                                                         | none          | on bar close                                            | —                 | the mirror row carries the word                 |
| CMP-197   | the rows                                                        | none          | ≤ once per frame from the crosshair                     | latest            | `aria-hidden`                                   |

### Density

| Component | Mode        | Row / control height                                       | Padding tokens        | Smallest hit target              | Notes                                   |
| --------- | ----------- | ---------------------------------------------------------- | --------------------- | -------------------------------- | --------------------------------------- |
| CMP-199   | comfortable | rows 32 px; the eye 24 × 24                                | `space.inset.md` (12) | 24 × 24                          | E11-D02 D6                              |
| CMP-199   | compact     | rows 24 px; the eye 24 × 24                                | `space.inset.sm` (8)  | 24 × 24                          | the trading default                     |
| CMP-199   | dense       | rows 24 px (the floor); the eye 24 × 24                    | `space.inset.xs` (4)  | 24 × 24                          | a per-panel chart override (E11-D05 §6) |
| CMP-224   | comfortable | a 24 px pill                                               | `space.inset.sm`      | 24 × 24                          | —                                       |
| CMP-224   | compact     | a 20 px pill in a 24 px hit box                            | `space.inset.xs`      | 24 × 24 (the hit box)            | E11-D02 §12                             |
| CMP-197   | all three   | not interactive; padding `space.inset.md` / `sm` / `xs`    | per density           | —                                | E11-D05                                 |
| CMP-194   | all three   | geometry in CSS px, device-snapped; independent of density | —                     | — (the legend eye is the target) | E11-D02 §4.4                            |
| CMP-195   | all three   | glyph ≤ 12 px; an interactive marker padded to ≥ 24 px     | —                     | 24 × 24 where interactive        | spec §4.4                               |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all five  | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12), filled

**Tokens & visual**

- [x] Uses only published Tier-2 / Tier-3 tokens — the spec binds existing names (§2, resolved by the tool §10.2) and lists every new name as a PROPOSED change request (§10.5); zero hard-coded hex or px in the spec beyond the measured tables and E13-D02's px, which stand.
- [~] Verified in all three themes at both density modes — the matrix is measured in all three themes (§10.1); the frames are drawn in dark / light × compact / comfortable and high-contrast as specimens (BQ-3, RULED); BLOCKED-PENPOT until the boards exist.
- [x] Passes the automated contrast-matrix check for every pair it introduces or touches — the tool: 105 pairs × 3 themes, 57 gated, FAIL 0 (the `pairs.mjs` rows themselves land with the token PR, CR-5).
- [~] CVD simulation reviewed for any new colour-carrying state — computed now (84 slot-pair rows, 4 tritanopia-only collapses; 7,632 slot × reserved rows, four recorded residuals, §10.3); the `cvd_sim.py` run on the exports and E13-D05's review follow the boards.

**Behaviour & states**

- [~] Every documented State has a corresponding Penpot variant and Storybook story — the states are specified (spec §7.1, §8; Table 1) and the stories named; the Penpot frames are BLOCKED-PENPOT.
- [x] Disabled states use the disabled-with-reason pattern (CMP-079), never a bare disabled control — the Style tab's token controls under one tab-level reason ("Style tokens arrive with E13-D04"), the cap reasons (Add to chart, SCR-012's command, the D17 "Apply as new instance" at the cap), Remove's reason in both D24 variants, a locked item's Move / Remove ("Unlock to move or remove", D21) and the bulk Delete with a locked item selected (E13-D02 D5 / D10 / D11 / D17 / D21 / D22 / D24), plus the role, grant and session legs (view-as, `workspaces:write`, `rbac.account`, `rbac.account_read_only`) in CMP-079 RbacGate with one notice per frame — `rbac.view_as` on SCR-034 / SCR-035 / SCR-036 while viewing as (the first leg), `notice.panel_read_only` for a Viewer on SCR-035 / SCR-036; on SCR-036 by row kind: a drawing row's eye and lock are `updateDrawing` writes and point at the notice, an indicator row's eye and lock are session state and stay T1 (spec §12, G-11) — rendered as E09-D09 §2.2's T2 (spec §12: `aria-disabled`, the CMP-019 `lock` glyph, the full label in `color.text.tertiary`, the reason in `color.text.secondary`, in the DOM at mount); the in-flight Adding… / Subscribing… / Updating… / Applying… are loading (`aria-busy`), never T2; Apply on an invalid field is form validity (E09-D09 §9.1) in E30-D02 D3's look — the owner rule on `main`, "disabled = `opacity.disabled` on the control with the reason as full-opacity text under it, never inside it.": the primary fill and label at `opacity.disabled`, "Fix the highlighted field first." full-opacity `color.text.secondary` beside it, `aria-disabled`, no lock glyph, no CMP-079 (spec §12); the before-history row's non-owner leg is the sentence form "Recording is set up by the owner." — CMP-026 EmptyState with `cta` omitted (spec §7.1).
- [x] Loading / empty / error states are explicitly designed — E13-D02 §9 in colour (spec §8; boards 07, 08).
- [x] Demo / Live env context is visually unambiguous wherever the component can trigger a trading action — the blocked-removal rows keep the LIVE / DEMO word + icon badges (`color.env.*` on the icon and border only; spec §2).

**Consistency**

- [x] Reuses an existing CMP-\* rather than introducing a near-duplicate — no new component; E13-D02's G-1…G-4 are cited.
- [x] Storybook stories match the full Variants × States matrix stated in the catalogue entry — Table 1 (the catalogue's stories kept, the new ones PROPOSED in spec §16).
- [~] Component or screen composes only published-library Penpot components — the boards paint literal colours resolved from the token JSON (the lane's export rule); the DS library entries are E13-D04 / E13-D06's.

## B. Accessibility acceptance-criteria template (`05` §10), filled once for the on-chart series language

The three screens' keyboard contract, names and live regions are E13-D02 §11's (fixed, cited); this spec adds the focus-ring rendering only (spec §12). The template below covers the primary task this spec introduces: **tell two EMAs apart with hue removed; find the provisional leg; read a Supertrend flip without colour.**

```gherkin
Feature: Indicator series visual language (E13-D03) — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user moves the keyboard cursor over a pane with EMA 21, EMA 50, a Supertrend flip and a provisional Zig Zag leg
    Then every control involved (the legend rows, the eye toggles, the count chip, "+N more") is reachable via Tab / arrow-key navigation
    And every action has a documented non-drag keyboard equivalent (E13-D02 §11; Table 2)
    And focus is never silently moved by a background data update
    And a visible focus indicator meeting >= 3:1 contrast is present at every step (color.focus.ring: 6.15 / 5.39 / 15.99 on the overlay, 7.05 / 6.30 / 18.32 on the canvas)

  Scenario: Screen-reader operation
    Given the user is using NVDA with the keyboard
    When the cursor lands on a flip bar, a divergence bar or the provisional leg
    Then the mirror row reads "Supertrend flip up", "Bullish divergence" or "swing high 63,980 provisional" (spec §12)
    And live data follows E13-D02 §11.4: the legend values update visually only, never announced; the add / hidden / shown / needs-N-bars / error / rebuilt / applied events are announced once, polite
    And the canvas data has a working DOM mirror with full parity (E06-D03 D4; 26 §12)

  Scenario: Colour-independence
    Given two instances of EMA on one pane, a Bollinger channel, a Supertrend flip and a provisional leg
    When the frame is rendered in greyscale
    Then the second EMA differs by its ladder tier (spec §4.1; D4), the channel by its three edges and fill, the flip by its ▲ / ▼ glyph and the words "Flip up" / "Flip down", the leg by its dash and the word "provisional"
    And the palette passes deuteranopia / protanopia / tritanopia simulation review (84 slot-pair rows with 4 tritanopia-only collapses carried by the tier and every pair >= 8 dE in normal vision; 7,632 slot-vs-reserved rows with the four recorded residuals; spec §10.3)

  Scenario: Contrast
    Given the frame is rendered in the dark theme and the high-contrast theme
    Then all text meets >= 4.5:1 (legend label 15.20 / 17.21) and all meaning-carrying series ink meets >= 3:1 (every slot on the canvas; guide levels 5.96 / 11.87), per the token contrast matrix (spec §10.1)
    And the band fill at opacity.indicator.fill 0.20 keeps every candle token >= 3:1 (worst 3.26 under the candles, 3.04 over them; fills never compound)

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override)
    When a series is added, hidden, rebuilt or its theme switches
    Then the state flips with no transition and no flashing content (Table 4)

  Scenario: Automated gates
    Given the first story that renders the legend, the markers or a series is opened
    Then axe-core reports zero new serious/critical violations over the mirror and the chrome
    And the affected screen's Lighthouse Accessibility score remains >= 95
    And the keyboard-only E2E smoke test covering the legend's toggle and quick-edit passes
```

Screen-reader spot-testing is deferred to E13-D05 and E13-Q04 / the release-level pass (`05` §8) — stated, not assumed. No owner-approved exception exists.
