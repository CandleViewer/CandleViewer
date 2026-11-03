# E18-D03 — Hand-off (`16` §11.4): CMP-109, CMP-132, CMP-182 and CMP-228's `footprint` kind

The pack is [E18-D03.md](E18-D03.md): every "A-n" below is its §C row, applied to `15` and `16` by PR 2 (the boards PR); every "R-n", "W-n", "C-n" or "OQ-n" is the pack's. The keyboard tables add no global binding and leave `Esc` untouched (`05` §3). Boards are PENDING (the pack's §0): the Penpot file `E18-D03 boards`, page `E18-D03`, is referenced by page name and page id only (R32 R7).

The lines are `16` §11.4's thirteen, as `16` §11.2 / §11.4 and `02`:56 ask (the BQ ruling's missed row): Penpot link, variants × states, keyboard table, name / role table, live data, motion pair (N/A → E18-D04 #498), density notes, essential exceptions, tokens, data contract, contrast and CVD, design QA, sign-off.

Rule: every line is `[x]` with its evidence, or `[ ]` with its reason (a PR still to land, or `N/A — <reason>`); a line that does not apply is `[x]` with `N/A — <reason>`. No blank line at Done (`16` §11.4).

## Handoff checklist — CMP-109 FootprintCell (E18-D03, #497)

- [ ] **Final Penpot link** — file `E18-D03 boards`, page `E18-D03` (page id recorded at PR 2); boards 01–07 — PR 2
- [x] **Variants × States matrix** — Table 1; A-4, A-5
- [x] **Keyboard table** — Table 2
- [x] **Accessible name / role table** — Table 3; the composition of pack §6 (W-3)
- [x] **Live data** — Table 5
- [x] **Motion pair** — N/A — E18-D04 #498 owns the motion
- [x] **Density notes** — the density table; R-3
- [x] **Essential-exceptions log** — `E47-S02-TSE-01`: cells below 24 CSS px at maximum zoom-out (SC 2.5.8), SCR-045 the compensating alternative (`15`:1292)
- [x] **Tokens used** — equal to A-3 after PR 2; the PROPOSED names of pack §2.1 land in PR 2's token JSON through `16` §11.2 (G-2)
- [x] **Data contract confirmed** — `24` §4.1's footprint level (`24`:816: `bid_volume` is aggressor sell volume); the wire's imbalance and POC flags (pack §10)
- [x] **Contrast and CVD** — computed by the tool (pack §2.3–§2.5); the PM rows land with the token JSON (G-2)
- [ ] **Design QA checklist (16 §12)** — with the boards at PR 2
- [ ] **Sign-off** — owner `approved` on #497 (pending, #2701); CMP-109 through `15`'s owner's stamp

### Table 1 — Variants × States

| Variant                        | State            | Penpot variant                                             | Story name                | Notes                                |
| ------------------------------ | ---------------- | ---------------------------------------------------------- | ------------------------- | ------------------------------------ |
| any `cellMode` × `displayMode` | default          | CMP-109 · FootprintCell / Mode=…, Display=…, State=Default | the A-5 matrix cell       | fills by side (R-3)                  |
| any                            | imbalanced buy   | CMP-109 · FootprintCell / Imbalance=Buy                    | Imbalanced (Buy)          | right side-cell, or right half at L1 |
| any                            | imbalanced sell  | CMP-109 · FootprintCell / Imbalance=Sell                   | Imbalanced (Sell)         | left side-cell, or left half at L1   |
| any                            | point of control | CMP-109 · FootprintCell / State=Poc                        | PointOfControl            | rail and bold digits                 |
| any                            | forming          | CMP-109 · FootprintCell / State=Forming                    | Forming                   | cap, dimmed fills, the word          |
| any                            | stale            | CMP-109 · FootprintCell / State=Stale                      | Stale                     | data ink dimmed 15 %                 |
| any                            | LOD text hidden  | CMP-109 · FootprintCell / Lod=Hidden                       | LODTextHidden(zoomed-out) | fill, notch, marks                   |
| any                            | focused          | CMP-109 · FootprintCell / State=Focused                    | Focused                   | the level box, ≥ 3:1                 |
| any                            | CVD-safe         | CMP-109 · FootprintCell / Palette=CvdSafe                  | CvdSafe                   | the `color.cvd.*` twins              |

### Table 2 — Keyboard

| Key         | Action                                                               | Focus after              | Global conflict?          | Notes               |
| ----------- | -------------------------------------------------------------------- | ------------------------ | ------------------------- | ------------------- |
| `←` / `→`   | previous / next bar; a selected level keeps its price                | the plot                 | none (plot-local)         | E18-D02 §8.1        |
| `↑` / `↓`   | previous / next level of the cursor bar                              | the plot                 | none                      | the level box moves |
| `Enter`     | expands the cursor bar (≤ 40 nodes); on a level, opens CMP-046       | the drawer's title       | none                      | non-modal           |
| `Shift+F10` | the cell menu                                                        | the first item           | PROPOSED (E18-D02 GAP-12) | T2 items per R-4    |
| `Esc`       | closes the menu or the drawer, then clears the level, then collapses | the level, then the plot | none                      | —                   |

### Table 3 — Accessible name / role

| Element         | Role                      | Accessible name (source)                               | States / properties |
| --------------- | ------------------------- | ------------------------------------------------------ | ------------------- |
| a mirror level  | row (in the expanded bar) | the composition of pack §6 (W-3)                       | `aria-rowindex`     |
| the canvas cell | none                      | — (the canvas is `role="img"`, its summary the host's) | —                   |

### Table 5 — Live data

| Field                   | Politeness | Cadence          | Coalescing  | Notes                 |
| ----------------------- | ---------- | ---------------- | ----------- | --------------------- |
| a forming cell's values | none       | the 250 ms topic | latest only | never announced (R-5) |
| the focused level       | polite     | on a key press   | —           | once per move         |

### Density

| Density     | Size class    | `cellPadPx` | `lodBias` |
| ----------- | ------------- | ----------- | --------- |
| comfortable | `type.num.sm` | 4           | +1 px     |
| compact     | `type.num.xs` | 2           | 0         |
| dense       | `type.num.xs` | 1           | 0         |

## Handoff checklist — CMP-132 ImbalanceStackIndicator (E18-D03, #497)

- [ ] **Final Penpot link** — file `E18-D03 boards`, page `E18-D03`; boards 03, 04 and 09 — PR 2
- [x] **Variants × States matrix** — Table 1; the registered states stand (`15`:1635); A-7 adds the lane's words
- [x] **Keyboard table** — N/A — the entry's own keys are unchanged (`15` CMP-132 A11y)
- [x] **Accessible name / role table** — N/A — unchanged: the surrogate label of `15` CMP-132
- [x] **Live data** — N/A — unchanged (≤ 4 Hz, E25's)
- [x] **Motion pair** — N/A — E18-D04 #498
- [x] **Density notes** — N/A — chart geometry; weights do not change with density
- [x] **Essential-exceptions log** — none: the surrogate is at least 24 × 24 CSS px (`15` CMP-132 A11y)
- [x] **Tokens used** — `15` CMP-132's registered tokens and pattern ids, plus the PROPOSED bracket weights (pack §2.1) and `stroke.bracket.status` (pack §3.3, A-20)
- [x] **Data contract confirmed** — `15` CMP-132's, unchanged; the bracket's zone state is G-4 (E18-S08 #632)
- [x] **Contrast and CVD** — the brackets and the hatch on the canvas, both palettes (pack §2.4); the signatures (pack §3.1)
- [ ] **Design QA checklist (16 §12)** — with the boards at PR 2
- [ ] **Sign-off** — owner `approved` on #497 (pending, #2701); CMP-132 also through E25-D05's owner (C-3)

### Table 1 — Variants × States

| Variant | State               | Penpot variant                                              | Story name         | Notes                                     |
| ------- | ------------------- | ----------------------------------------------------------- | ------------------ | ----------------------------------------- |
| buy     | active              | CMP-132 · ImbalanceStackIndicator / Side=Buy, State=Active  | ActiveBuy          | right lane, 3 px                          |
| buy     | tested              | CMP-132 · ImbalanceStackIndicator / Side=Buy, State=Tested  | TestedBuy          | right lane, 2 px, `pattern.dashed.tested` |
| buy     | broken              | CMP-132 · ImbalanceStackIndicator / Side=Buy, State=Broken  | BrokenBuy          | right lane, 1 px, `pattern.hatch.absent`  |
| sell    | active              | CMP-132 · ImbalanceStackIndicator / Side=Sell, State=Active | ActiveSell         | left lane, 3 px                           |
| sell    | tested              | CMP-132 · ImbalanceStackIndicator / Side=Sell, State=Tested | TestedSell         | left lane, 2 px, `pattern.dashed.tested`  |
| sell    | broken              | CMP-132 · ImbalanceStackIndicator / Side=Sell, State=Broken | BrokenSell         | left lane, 1 px, `pattern.hatch.absent`   |
| any     | selected            | CMP-132 · ImbalanceStackIndicator / State=Selected          | Selected           | full label, level boxes                   |
| any     | inherited-estimated | CMP-132 · ImbalanceStackIndicator / State=Estimated         | InheritedEstimated | the word; the registered patterns kept    |

## Handoff checklist — CMP-182 FootprintSeries (E18-D03, #497)

- [ ] **Final Penpot link** — file `E18-D03 boards`, page `E18-D03`; boards 01, 02, 03 and 05 — PR 2
- [x] **Variants × States matrix** — Table 1; A-9
- [x] **Keyboard table** — CMP-109's Table 2 (the series hosts the cursor)
- [x] **Accessible name / role table** — CMP-109's Table 3; the badge sentence joins the chart's description (E18-D02 §5.1)
- [x] **Live data** — CMP-109's Table 5; the badge once per tier change (R-5)
- [x] **Motion pair** — N/A — E18-D04 #498
- [x] **Density notes** — CMP-109's density table
- [x] **Essential-exceptions log** — CMP-109's (`E47-S02-TSE-01`)
- [x] **Tokens used** — equal to A-8 after PR 2
- [x] **Data contract confirmed** — CMP-109's; the series is `24` §4.1's bars
- [x] **Contrast and CVD** — pack §2.4 (every series mark)
- [ ] **Design QA checklist (16 §12)** — with the boards at PR 2
- [ ] **Sign-off** — owner `approved` on #497 (pending, #2701); CMP-182 through `15`'s owner's stamp

### Table 1 — Variants × States

| Variant     | State           | Penpot variant                             | Story name               | Notes                    |
| ----------- | --------------- | ------------------------------------------ | ------------------------ | ------------------------ |
| text shown  | L0 / L1         | CMP-182 · FootprintSeries / Zoom=High      | HighZoom(text visible)   | the halo on every glyph  |
| text hidden | L2              | CMP-182 · FootprintSeries / Zoom=Low       | LowZoom(LOD text hidden) | the notch; the badge W-8 |
| every mode  | default         | CMP-182 · FootprintSeries / Mode=All       | AllCellModes             | four modes               |
| densities   | default         | CMP-182 · FootprintSeries / Density=…      | Densities                | R-3                      |
| collapse    | L2, L3          | CMP-182 · FootprintSeries / State=Collapse | Collapse, L3Hidden       | box and profile          |
| markers     | default         | CMP-182 · FootprintSeries / Markers=On     | MarkersPocVaLedge        | rail, ticks, ledge       |
| forming     | forming, closed | CMP-182 · FootprintSeries / State=Forming  | FormingAndClosed         | the cap                  |

## Handoff checklist — CMP-228 PreviewTile, `footprint` kind (E18-D03, #497)

- [ ] **Final Penpot link** — file `E18-D03 boards`, page `E18-D03`; board 08 — PR 2
- [x] **Variants × States matrix** — Table 1; A-10
- [x] **Keyboard table** — N/A — `role="img"`, not focusable
- [x] **Accessible name / role table** — `role="img"`, named by W-18 (A-10)
- [x] **Live data** — N/A — sample data only; redrawn per settings change
- [x] **Motion pair** — N/A — none; a recomputing tile keeps its last frame (`15` CMP-228)
- [x] **Density notes** — the pane's density (E18-D02 §6.7)
- [x] **Essential-exceptions log** — none: the tile is not interactive
- [x] **Tokens used** — CMP-228's own plus CMP-109's
- [x] **Data contract confirmed** — N/A — sample data only, never a live or recorded feed
- [x] **Contrast and CVD** — CMP-109's (pack §2.3)
- [ ] **Design QA checklist (16 §12)** — with the boards at PR 2
- [ ] **Sign-off** — owner `approved` on #497 (pending, #2701); CMP-228 through `15`'s owner's stamp

### Table 1 — Variants × States

| Variant     | State         | Penpot variant                                          | Story name       | Notes                 |
| ----------- | ------------- | ------------------------------------------------------- | ---------------- | --------------------- |
| `footprint` | live settings | CMP-228 · PreviewTile / Kind=Footprint, State=Live      | Footprint        | SYNTHETIC bar         |
| `footprint` | CVD-safe      | CMP-228 · PreviewTile / Kind=Footprint, Palette=CvdSafe | FootprintCvdSafe | the twins             |
| `footprint` | dense         | CMP-228 · PreviewTile / Kind=Footprint, Density=Dense   | FootprintDense   | chart density         |
| `footprint` | empty / error | CMP-228 · PreviewTile / Kind=Footprint, State=Error     | Empty, Error     | "Preview unavailable" |

## Who applies what

PR 2 (the boards PR) applies A-1 … A-14 to `15` and `16` byte for byte after their owners stamp them and lands the token JSON and the pair rows through `16` §11.2 (G-2); E18-S06 #589 the engine uniforms; E18-S01 / E18-S11 #741 build CMP-109 and CMP-182; E18-S08 #632 the brackets; E18-S10 #674 the tile.
