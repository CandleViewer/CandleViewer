# E13-D04 — Per-component handoff checklist (`16` §11.4), the deltas on E13-D03's

Shared tables with a leading `Component` column — the E11-D05 / E25-D05 / E30-D03 / E13-D03 shape (one `16` §11.4 block per component contract this ticket changes, every line kept; Tables 1–5, the Density table and the Essential-exceptions table once each). This ticket **publishes** the tokens, ladders and variants four of E13-D03's five contracts consume: each block below is a **delta** on `docs/design/E13/E13-D03-handoff.md` at `f437dc6b4d75e69a3fd2484d6b9422785e5d6d25` — a cell that reads "as E13-D03-handoff :n" is unchanged there; CMP-197 ChartTooltip's contract is unchanged (the tooltip fade is E11-D06 row 12, already in `15` :2376) and keeps E13-D03's block. Status: owner approval pending; the boards PENDING (BLOCKED-PENPOT: page `E13-D04 Indicator palette and motion`, by name, its id pinned once created); the token PR pending (E05-T01's — BQ-4's rider, one carrier per row; the rows in `E13-D04.md` §2.3). Spec: `docs/design/E13/E13-D04.md`; tokens: `packages/ui/tokens` at `f364826c5a4dfff2da10060b0a4ec9918035911b`; numbers: `docs/design/_tools/e13_d04_palette_motion_audit.py` (the palette, the alpha and the CVD table regenerated through `e13_d03_palette_audit.py`, `--check` drift 0; the motion kinematics computed).

## Handoff checklist — CMP-194 IndicatorOverlay (E13-D04, #315)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING: page `E13-D04 Indicator palette and motion` (created by name on the board script's first run; id pinned here once it exists); planned PNGs `docs/design/E13/img/E13-D04-01-palette-token-sheet.png`, `E13-D04-02-palette-token-sheet-light.png`, `E13-D04-03-ladders-and-variants.png`, `E13-D04-06-motion-timelines.png`; the DS library entry is the token set and the story list of spec §12; the Penpot DS-library step is E05 Runbook A's (spec G-18)
- [ ] **Variants × States matrix** — PENDING the boards: the six line tiers, three bar tiers and three band tiers as published ids (spec §3) × the states as E13-D03-handoff :10, plus **re-computing** (spec §6 M6: the new draw at full alpha from frame 0, the old draw fading over `motion.duration.fast`; a cut under reduced motion); Table 1
- [ ] N/A — **Keyboard table**: as E13-D03-handoff :11 (the overlay is not focusable); Table 2 carries the legend's keys
- [x] **Accessible name / role table** — as E13-D03-handoff :12 (named by its legend row, valued by the mirror); Table 3
- [x] **Live data** — as E13-D03-handoff :13; a re-compute swaps the buffer and is announced once per commit by the legend's event line ("EMA 34 applied"), never per frame; Table 5
- [x] **Motion pair** — **M6** the series re-compute: `motion.duration.fast` + `motion.easing.standard` on one alpha uniform of the retained old batch (0.59 / 0.27 / 0.12 / 0.05 / 0.01 / 0.00 over the six 60 fps frames), the new series at full alpha from frame 0, never an interpolation of values; reduce → a cut; the implementing engine ticket may fall back to the cut if the frame budget binds on the reference dataset — the bench decides (BQ-6 RULED, issuecomment-6364739361); a theme switch stays a LUT re-upload (`26` §5 rule 1, no transition); Table 4
- [x] **Density notes** — as E13-D03-handoff :15 (geometry in CSS px, device-snapped, density-independent); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — the published names: `color.indicator.palette.1` … `color.indicator.palette.8`, `opacity.indicator.fill`, `size.stroke.thin` / `size.stroke.regular` / `size.stroke.bold` (CR-1 / CR-2, pending the token PR — no longer "PROPOSED" names, published by spec §2), `color.candle.up` / `color.candle.down`, `color.text.tertiary`, `color.surface.canvas`; the registry ids `dash.solid` / `dash.8-4` / `dash.8-3-2-3`, `bar.full` / `bar.narrow` / `bar.outline` (spec §3); `motion.duration.fast` + `motion.easing.standard` (M6); none invented; Penpot token sets = `packages/ui/tokens` at `f364826c5a4dfff2da10060b0a4ec9918035911b`
- [x] **Data contract confirmed** — as E13-D03-handoff :18; the `style` object carries spec §4's closed vocabulary (five keys; the contract PR is E13-T03's, spec G-12)
- [ ] **Contrast and CVD** — PENDING the token PR's `pairs.mjs` rows (CR-5) and the `cvd_sim.py` run on the exports: spec §2.1 / §2.5 (the tool's sections 2–3, equal to E13-D03's) — every slot ≥ 3:1 on the canvas in all three themes (lowest 3.05), ≥ 8 ΔE from every reserved token (smallest 8.3) and from every other slot (smallest 14.2); 84 slot-pair CVD rows with 1 tritanopia-only collapse; the band fill at 0.20 keeps the worst candle ratio 3.26:1 under / 3.04:1 over / 3.50:1 CVD-safe; the half-faded old draw (1.61–3.06:1 over the canvas) is decorative — the new draw carries the values
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — CMP-195 AnnotationMarker (E13-D04, #315)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING: page `E13-D04 Indicator palette and motion`; planned PNG `docs/design/E13/img/E13-D04-03-ladders-and-variants.png`
- [ ] **Variants × States matrix** — PENDING the boards: `glyph.diamond` / `glyph.disc` / `glyph.square` (identity), ▲ / ▼ with "Flip up" / "Flip down" (direction), `icon/divergence` with its words, the provisional pivot (`pattern.dashed.provisional` + "provisional") × confirmed / provisional / hidden with its series (spec §3.4); Table 1
- [ ] N/A — **Keyboard table**: as E13-D03-handoff :30 (not focusable; the mirror row reads the word)
- [x] **Accessible name / role table** — as E13-D03-handoff :31; Table 3
- [x] **Live data** — as E13-D03-handoff :32; Table 5
- [x] **Motion pair** — none animated: a marker's appearance on bar close is a state flip (E11-D06 D15; `motion.duration.instant`, identical in both modes); Table 4
- [x] **Density notes** — as E13-D03-handoff :34; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — the instance's slot `color.indicator.palette.1` … `color.indicator.palette.8` (published, spec §2), `color.text.primary`, `color.surface.canvas`; the ids `glyph.diamond` / `glyph.disc` / `glyph.square`, `icon/divergence`, `pattern.dashed.provisional` (CR-3 / CR-7); `color.marker.*` does not exist and is not proposed (E13-D03 C-20); Penpot token sets = `packages/ui/tokens` at `f364826c5a4dfff2da10060b0a4ec9918035911b`
- [x] **Data contract confirmed** — as E13-D03-handoff :37
- [ ] **Contrast and CVD** — PENDING as CMP-194: the glyph takes the slot's measured ratios (spec §2.1); direction and divergence carry words, so no CVD pair is relied on
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-199 ChartLegend (E13-D04, #315)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING: page `E13-D04 Indicator palette and motion`; planned PNGs `docs/design/E13/img/E13-D04-04-legend-chip-variant-matrix.png`, `E13-D04-05-legend-chip-variant-matrix-light.png`, `E13-D04-06-motion-timelines.png`, `E13-D04-07-themes-state-matrix.png`
- [ ] **Variants × States matrix** — PENDING the boards: the four variant additions `ribbon` (collapsed / expanded), `errored`, `warming-up`, `provisional` (spec §5.1) × per density (32 / 24 / 24) × three themes, beside the normal row; the quick-edit commit **T2** while viewing as (`rbac.view_as`, the lock glyph, the full label, the reason under the row; inset `quick-edit-t2`) and for a Viewer (`rbac.permission` under the one header notice; the named inset `quick-edit-viewer`); row add (M7) and row remove (M8); Table 1
- [x] **Keyboard table** — as E13-D03-handoff :68 (E11-D02 D12 / E13-D02 §11 unchanged); on a T2 commit `Enter` commits nothing and re-shows the reason once, politely (E09-D09 §9.3); Table 2
- [x] **Accessible name / role table** — as E13-D03-handoff :69; the variant words "ribbon" (the five lengths), "error", "34 more bars needed", "provisional" are already in the names; Table 3
- [x] **Live data** — as E13-D03-handoff :70; the warming-up count recomputes as bars arrive and is announced once ("EMA 200 needs 34 more bars"), never per bar; Table 5
- [x] **Motion pair** — **M7** row add: `motion.duration.fast` + `motion.easing.standard` opacity fade-in at the final position (no slide), reduce → instant (the row with "—" and "computing…" is the carrier); **M8** row remove: frame 0, identical in both modes (the toast "EMA 21 removed." with "Undo" and the announcement carry it); **M4 / M5** the sub-pane create / collapse the pane-label row rides on: `motion.duration.normal` + `motion.easing.standard` translate + clip (E11-D06 D18), reduce → instant with the tree row, the toast and the announcement; the state words, the swatch and the eye are state flips (D15); the "+N more" popover `fast` → instant (E11-D06 row 39); Table 4
- [x] **Density notes** — as E13-D03-handoff :72 (rows 32 / 24 / 24; the 24 × 24 eye); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — inherits CMP-037; `color.indicator.palette.1` … `color.indicator.palette.8` for the swatch (published, spec §2), `color.text.primary`, `color.text.secondary`, `color.text.tertiary` (hidden, stale; the T2 label and lock glyph), `color.status.danger.strong` / `color.status.warning.strong`, `color.surface.canvas`, `color.surface.hover`, `color.surface.raised` + `color.border.default` (the T2 fill and hairline), `color.surface.overlay` + `elevation.popover`, `color.text.link`, `color.focus.ring`, `type.num.*`, `type.ui.label`, `type.ui.caption`, `space.inset.sm` / `space.inset.xs`, `size.control.height`; `motion.duration.fast` + `motion.easing.standard` (M7, the popover), `motion.duration.normal` + `motion.easing.standard` (M4 / M5), `motion.duration.instant` (M8, M9); CMP-079 RbacGate · CMP-019 Icon `lock` on the gated commit; none invented; Penpot token sets = `packages/ui/tokens` at `f364826c5a4dfff2da10060b0a4ec9918035911b`
- [x] **Data contract confirmed** — as E13-D03-handoff :75
- [ ] **Contrast and CVD** — PENDING the token PR's rows and the export run: spec §11.1 — label 15.20 / 16.78 / 17.21, value 9.33 / 9.65 / 15.20, hidden 5.96 / 6.36 / 11.87, the error glyph 9.87 / 4.41 / 9.87, the T2 label 5.62 / 5.92 / 11.21 and reason 8.81 / 8.98 / 14.35 on raised, the ring 7.05 / 6.30 / 18.32; the swatch takes the slot's ratios; the half-faded row label (4.61 / 3.36 / 5.02 over the canvas) is decorative — the row's words carry it within 100 ms
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-224 IndicatorChips (E13-D04, #315)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING: page `E13-D04 Indicator palette and motion`; planned PNGs `docs/design/E13/img/E13-D04-04-legend-chip-variant-matrix.png`, `E13-D04-05-legend-chip-variant-matrix-light.png`, `E13-D04-07-themes-state-matrix.png`
- [ ] **Variants × States matrix** — PENDING the boards: `Ind 0` · `Ind 4` · `Ind 4 · 1 hidden` · `Ind 4 · 1 error` · `Ind 4 · 2 stale` · `Ind 4 · 1 computing` · `Ind 20` · focused × compact / comfortable × three themes (spec §5.2); Table 1
- [x] **Keyboard table** — as E13-D03-handoff :87; Table 2
- [x] **Accessible name / role table** — as E13-D03-handoff :88; Table 3
- [x] **Live data** — as E13-D03-handoff :89; Table 5
- [x] **Motion pair** — **M9**: the count and the suffix are state flips, instant in both modes (E11-D06 D15; `motion.duration.instant`); Table 4
- [x] **Density notes** — as E13-D03-handoff :91; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.surface.raised`, `color.text.tertiary` (the border; the hidden glyph), `color.text.primary`, `color.status.danger.strong` / `color.status.warning.strong` / `color.status.info.strong`, `radius.pill`, `type.ui.caption`, `color.focus.ring`; `motion.duration.instant`; none invented; Penpot token sets = `packages/ui/tokens` at `f364826c5a4dfff2da10060b0a4ec9918035911b`
- [x] **Data contract confirmed** — as E13-D03-handoff :94
- [ ] **Contrast and CVD** — PENDING the token PR's rows: as E13-D03-handoff :95 (the words 14.35 / 15.62 / 16.25 on raised, the error glyph 9.32 / 4.11 / 9.32, the ring 6.66 / 5.86 / 17.30); the hue rides on the glyph only
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

### Table 1 — Variants × States (delta rows; the rest as E13-D03-handoff Table 1 :100–:109)

| Component | Variant                              | State (every one a Penpot frame on the boards of spec §0 and a story)                                                                                                                              | Penpot frame (board) | Story name(s)                                                                  |
| --------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------------------------------------------------------------------------------ |
| CMP-194   | the published tiers (ids of spec §3) | as E13-D03 · **re-computing** (M6: frame 0 / 50 ms / 100 ms; the cut twin)                                                                                                                         | 03, 06               | as E13-D03 + RecomputeCrossFade, RecomputeReducedMotion                        |
| CMP-195   | as E13-D03 (ids of spec §3.4)        | as E13-D03                                                                                                                                                                                         | 03                   | as E13-D03                                                                     |
| CMP-199   | `ribbon`                             | collapsed (▸ ≡, the five lengths) · expanded (five sub-rows, one hue in five tiers)                                                                                                                | 04, 05               | Ribbon, RibbonExpanded                                                         |
| CMP-199   | `errored`                            | `icon/warning` + "error", value "—", the detail message; the eye operable                                                                                                                          | 04, 05               | Errored                                                                        |
| CMP-199   | `warming-up`                         | "34 more bars needed" + `icon/bars-missing`; the hatched warm-up tile "warm-up · 34 more bars"                                                                                                     | 04, 05               | WarmingUp                                                                      |
| CMP-199   | `provisional`                        | "provisional" after the value; ╌ beside ◆ in the swatch                                                                                                                                            | 04, 05               | Provisional                                                                    |
| CMP-199   | the editing state's gated commit     | **T2** while viewing as (`rbac.view_as`) and for a Viewer (`rbac.permission`): the lock glyph, the full label, the reason under the row — the named insets `quick-edit-t2` and `quick-edit-viewer` | 04, 05               | QuickEditViewAs (both reasons)                                                 |
| CMP-199   | row add / row remove (M7 / M8)       | fade-in at 0 / 50 / 100 ms; the instant twin; the frame-0 leave with the toast                                                                                                                     | 06                   | RowAdd, RowAddReducedMotion                                                    |
| CMP-224   | the count chip (spec §5.2)           | `Ind 0` · `Ind 4` · `Ind 4 · 1 hidden` · `Ind 4 · 1 error` · `Ind 4 · 2 stale` · `Ind 4 · 1 computing` · `Ind 20` · focused · the flip (M9)                                                        | 04, 05, 06, 07       | None, Several, WithHidden, WithError, WithComputing, WithStale, AtCap, Focused |

### Table 2 — Keyboard

| Component | Key                                              | Action                                                                           | Focus after | Global conflict? | Notes    |
| --------- | ------------------------------------------------ | -------------------------------------------------------------------------------- | ----------- | ---------------- | -------- |
| all four  | as E13-D03-handoff Table 2 :110–:125             | unchanged                                                                        | —           | none             | —        |
| CMP-199   | `Enter` on a T2 quick-edit (viewing as / Viewer) | commits nothing; re-shows the reason under the row once, politely (E09-D09 §9.3) | the field   | none             | spec §13 |

### Table 3 — Accessible name / role

| Component | Element                              | Role      | Accessible name (source)                   | States / properties                                                    |
| --------- | ------------------------------------ | --------- | ------------------------------------------ | ---------------------------------------------------------------------- |
| all four  | as E13-D03-handoff Table 3 :126–:138 | unchanged | the variant words are already in the names | the T2 commit: `aria-disabled="true"`, `aria-describedby` → the notice |

### Table 4 — Motion pair (every "E13-D04's (not specified here)" row of E13-D03-handoff :143 replaced)

| Component | Property                                                       | motion-safe                                                                                                                                        | motion-reduce                                                                   | Duration / easing tokens                           |
| --------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------- |
| CMP-199   | row add (M7)                                                   | opacity fade-in at the final position, no slide                                                                                                    | instant; the row with "—" and "computing…" carries it                           | `motion.duration.fast`, `motion.easing.standard`   |
| CMP-199   | row remove (M8)                                                | none — the row leaves at frame 0                                                                                                                   | identical; the toast and the announcement carry it                              | `motion.duration.instant`                          |
| CMP-199   | the sub-pane create / collapse its pane row rides on (M4 / M5) | translate + clip over the pane boundary (E11-D06 D18); the panes at their final geometry on frame 0                                                | instant; the pane header, the tree row, the toast and the announcement carry it | `motion.duration.normal`, `motion.easing.standard` |
| CMP-199   | state words, the swatch, the eye                               | state flips (E11-D06 D15)                                                                                                                          | identical                                                                       | `motion.duration.instant`                          |
| CMP-199   | the "+N more" popover                                          | `fast` fade (E11-D06 row 39)                                                                                                                       | instant                                                                         | `motion.duration.fast`                             |
| CMP-224   | the count and the suffix (M9)                                  | state flip (E11-D06 D15)                                                                                                                           | identical                                                                       | `motion.duration.instant`                          |
| CMP-194   | the series re-compute (M6)                                     | the new draw at full alpha from frame 0; the retained old draw fades through one alpha uniform (0.59 / 0.27 / 0.12 / 0.05 / 0.01 / 0.00 at 60 fps) | a cut; the legend value and the once-per-commit announcement carry it           | `motion.duration.fast`, `motion.easing.standard`   |
| CMP-194   | a theme switch                                                 | a LUT re-upload, no transition (`26` §5 rule 1)                                                                                                    | identical                                                                       | none                                               |
| CMP-195   | a marker's appearance on bar close                             | a state flip                                                                                                                                       | identical                                                                       | `motion.duration.instant`                          |

### Table 5 — Live data

| Component | Field                                | Politeness | Cadence | Coalescing | Notes                                                      |
| --------- | ------------------------------------ | ---------- | ------- | ---------- | ---------------------------------------------------------- |
| all four  | as E13-D03-handoff Table 5 :151–:162 | unchanged  | —       | —          | a re-compute is announced once per commit, never per frame |

### Density

| Component | Mode                                 | Row / control height | Padding tokens | Smallest hit target | Notes                                                                    |
| --------- | ------------------------------------ | -------------------- | -------------- | ------------------- | ------------------------------------------------------------------------ |
| all four  | as E13-D03-handoff Density :163–:175 | unchanged            | —              | 24 × 24             | the sub-pane floor 48 px and the ladder geometry are density-independent |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all four  | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12), filled for this spec's scope

- [x] Uses only published Tier-2 / Tier-3 tokens — every existing name resolved by the tool; the new names (`color.indicator.palette.1` … `.8`, `opacity.indicator.fill`, `size.stroke.*`) are this spec's publication with copy-ready rows for the token PR (spec §2.3); zero hard-coded hex or px beyond the measured tables and E13-D02's px.
- [~] Verified in all three themes at both density modes — measured in all three themes (spec §2.1, §11.1); the boards are PENDING.
- [x] Passes the automated contrast-matrix check for every pair it introduces or touches — spec §11.1 FAIL 0 (the `pairs.mjs` rows land with the token PR, CR-5).
- [~] CVD simulation reviewed for any new colour-carrying state — computed (spec §2.5); the export run and E13-D05's review follow the boards.
- [~] Every documented State has a Penpot variant and a Storybook story — specified (Table 1; spec §12); the frames are PENDING.
- [x] Disabled states use the disabled-with-reason pattern (CMP-079), never a bare disabled control, for any RBAC / env-gated action — the quick-edit commit while viewing as / for a Viewer and the Style tab's token controls under one tab-level reason (spec §13); form validity keeps the LANE-55 look, never a lock.
- [x] Loading / empty / error states explicitly designed — E13-D03 §7.1's; the `errored` and `warming-up` variants (spec §5.1).
- [x] Keyboard-interaction table completed — Table 2 (unchanged plus the T2 commit).
- [x] Accessible-name / role table completed — Table 3.
- [x] Canvas-adjacent components' DOM-mirror strategy specified — as E13-D03 (the mirror; the legend row); nothing deferred.
- [x] Motion-safe / motion-reduce pair specified for any animated property — Table 4; spec §6 / §7 (9 rows, 9 twins).
- [x] Hit targets ≥ 24 px (compact) — as E13-D03's Density table.
- [~] Accessibility role signed off — E13-D05 in flight; the owner's `approved` pending.
- [x] Trading-specific safety — no component here places an order; the DEMO / LIVE badges are unchanged; no palette slot aliases the env primitives (E13-D03 §3.2).
- [x] Any heuristic / estimated value chip-tagged — no v1 indicator series is estimated; "(estimated)" by reference, in full.
- [x] Reuses an existing CMP-\* — no new component.
- [x] Storybook stories match the Variants × States matrix — Table 1 and spec §12.
- [~] Composes only published-library Penpot components — the boards paint literal colours resolved from the token JSON (the lane's export rule); the DS library entries: the token set and the story list are this spec's; the Penpot DS-library step is E05 Runbook A's (spec G-18).

## B. Accessibility acceptance-criteria template (`05` §10), filled once for the motion

The three screens' keyboard contract, names and live regions are E13-D02 §11's and E13-D03 §12's (cited); the series language's scenarios are E13-D03-handoff §B's. The template below covers what this spec adds: **the motion and its reduced-motion twins.**

```gherkin
Feature: Indicator motion and its reduced-motion twins (E13-D04) — accessibility acceptance criteria

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override), resolved as data-motion="reduce"
    When SCR-034, SCR-035 or SCR-036 opens or closes (M1–M3), a sub-pane is created or collapses (M4 / M5),
      a series is re-computed after a commit (M6), or a legend row is added or removed (M7 / M8)
    Then the feature uses the motion-reduce variant: an instant state change (a cut for M6) that keeps the same
      information through its static carrier — focus and the title, the pane header and the tree row, the legend
      value and "computing…", the toast "EMA 21 removed." with "Undo", the announcement once —
    And no content flashes more than 3 times per second (every row <= 1 luminance change per second) and no motion
      lasts > 5 s (nothing loops)
    And no affordance is removed (Undo, the eye, the quick-edit, the tabs and the fields stay where they were)

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user adds RSI to a new sub-pane, removes it, applies EMA 34 and re-opens the drawer
    Then every step is one frame of layout under reduce and the same frame-to-frame path under motion-safe
      (the keyboard path and the reduce path coincide for the pane rows; E11-D06 §9.2)
    And focus lands and returns per E13-D02 §11.2 and a visible focus indicator meeting >= 3:1 is present

  Scenario: Screen-reader operation
    Given the user is using NVDA with the keyboard
    When a sub-pane appears or leaves, a series is re-computed or a row is added or removed
    Then the add / removal / applied events are announced once, polite (E13-D02 §11.4); nothing is announced per frame or per tick
    And the T2 quick-edit commit announces the name, "unavailable" and the reason once

  Scenario: Colour-independence and contrast
    Given the frame is rendered in greyscale and in the high-contrast theme
    Then every motion's carrier is a word, a glyph, a boundary or a row — never a hue; every gated pair of spec §11.1
      meets >= 4.5:1 (text) or >= 3:1 (non-text), and the decorative composites are not relied on

  Scenario: Automated gates
    Given the first story that renders the legend, a sub-pane or a re-computing series is opened
    Then axe-core reports zero new serious/critical violations over the mirror and the chrome
    And the keyboard-only E2E smoke test covering the legend's toggle, quick-edit and the drawer's open / close passes
```

Screen-reader spot-testing is deferred to E13-D05 and the release-level pass (`05` §8) — stated, not assumed. No owner-approved exception exists.
