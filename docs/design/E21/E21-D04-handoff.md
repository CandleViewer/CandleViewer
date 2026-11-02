# E21-D04 — Hand-off (`16` §11.4): the seven component checklists

Components: CMP-108, CMP-111, CMP-113, CMP-227, CMP-228, CMP-229 and CMP-230. The pack is [E21-D04.md](E21-D04.md): every "A-n" below is its §C row, applied to `15` by PR 2, and every "R-n", "W-n", "C-n" or "OQ-n" is the pack's. The keyboard tables add no global binding (`05` §3.2) and leave `Esc` and `Ctrl+K` untouched (`05` §3.3). Boards are PENDING (the pack's §0): no Penpot link exists yet, and none is ever an instance URL (R32 R7).

Rule: every line is `[x]` with its evidence, or `[ ]` with its reason (a PR still to land, or `N/A — <reason>`); a line that does not apply is `[x]` with `N/A — <reason>`, the E09-D07 precedent, which `16` §13.3 item 8 accepts. No blank line at Done (`16` §11.4, §13.3).

## Handoff checklist — CMP-108 DomLadderRow (E21-D04, #504)

- [ ] **Final Penpot link** — file `E21-D04 boards`, page `E21-D04` (page id recorded at PR 3); specimen frames `CMP-108 · DomLadderRow / Variant=…, State=…` on boards 01, 02, 09 and 10 — PR 3
- [x] **Variants × States matrix** — table 1; A-3, A-7
- [x] **Keyboard table** — table 2; A-4
- [x] **Accessible name / role table** — table 3; the label template (pack §4.1)
- [x] **Live data** — table 5
- [x] **Motion pair** — N/A — none animated (follow and scrim motion are E21-D05 #505's)
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to A-5 after PR 2; no token invented; token sets = `packages/ui/tokens` at `9b77e6b83`
- [x] **Data contract confirmed** — props only, from an already-filtered caller; callbacks only (A-6; R-1)
- [x] **Contrast and CVD** — computed by the tool (pack §5.4: the text on both bar fills, the text and the stale word on the stale surface, the ring); no new pair for `tools/contrast/pairs.mjs`
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — owner `approved` on #504 (pending, #2701)

### Table 1 — Variants × States

| Variant           | State                     | Penpot variant                                             | Story name             | Notes                        |
| ----------------- | ------------------------- | ---------------------------------------------------------- | ---------------------- | ---------------------------- |
| bid-side          | default                   | CMP-108 · DomLadderRow / Variant=BidSide, State=Default    | BidSide                | size bar `color.buy.subtle`  |
| ask-side          | default                   | CMP-108 · DomLadderRow / Variant=AskSide, State=Default    | AskSide                | size bar `color.sell.subtle` |
| best bid / ask    | default                   | CMP-108 · DomLadderRow / Variant=Best, State=Default       | BestBidAsk             | the "best bid" clause        |
| at-mark           | default                   | CMP-108 · DomLadderRow / Variant=AtMark, State=Default     | AtMark                 | the "at the mark" clause     |
| own-order present | default                   | CMP-108 · DomLadderRow / Variant=OwnOrder, State=Default   | WithOwnOrders          | CMP-230 single               |
| own-order present | aggregate                 | CMP-108 · DomLadderRow / Variant=OwnOrder, State=Aggregate | OwnOrderAggregate      | CMP-230 aggregate            |
| position          | default                   | CMP-108 · DomLadderRow / Variant=Position, State=Default   | WithPosition           | W-9                          |
| stale             | default                   | CMP-108 · DomLadderRow / Variant=Stale, State=Default      | Stale                  | stale surface + the word     |
| estimated         | default                   | CMP-108 · DomLadderRow / Variant=Estimated, State=Default  | Estimated              | the word "estimated"         |
| any               | focus-visible             | CMP-108 · DomLadderRow / Variant=BidSide, State=Focus      | FocusVisible           | CMP-039 outside the row      |
| any               | menu-open, trade items T2 | CMP-108 · DomLadderRow / Variant=BidSide, State=MenuT2     | MenuOpen, TradeItemsT2 | R-3; CMP-079; `lock`         |
| any               | virtualised window        | —                                                          | VirtualisedWindow      | only visible rows in the DOM |

### Table 2 — Keyboard

| Key           | Action                                                       | Focus after           | Global conflict?                    | Notes                                                                       |
| ------------- | ------------------------------------------------------------ | --------------------- | ----------------------------------- | --------------------------------------------------------------------------- |
| `↑` / `↓`     | previous / next row                                          | the new row           | none (grid-local)                   | roving, one tab stop, keyed by price                                        |
| `←` / `→`     | across the row's cells (D02 §9.2)                            | the next cell         | none (grid-local)                   | each a `gridcell` named by its text                                         |
| `Enter`       | opens the row action menu (CMP-041)                          | the menu's first item | `05`'s limit key: C-3, E21-D06 #506 | trade items T2 (R-3); on an aggregate's Your-orders cell it expands CMP-230 |
| `Delete`      | cancels the row's one own order; on an aggregate, expands it | stays on the row      | none                                | never cancels all; W-21 … W-23 once (R-5); never gated on the arm (R-4)     |
| `Shift+Enter` | opens CMP-111's reveal for the price                         | the reveal's heading  | PROPOSED (OQ-1)                     | E21-D06 rules it                                                            |
| `Esc`         | closes the menu or the reveal                                | back to the row       | none (`Esc` keeps its meaning)      | —                                                                           |

### Table 3 — Accessible name / role

| Element  | Role            | Accessible name (source)                                       | States / properties                                                                           |
| -------- | --------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| the row  | row (in a grid) | the label template of pack §4.1 (W-1 is its normative example) | `aria-rowindex`; no `aria-selected` (no row selection exists; focus is the roving `tabindex`) |
| size bar | none            | `aria-hidden` (the number carries the size)                    | —                                                                                             |

### Table 5 — Live data

| Field            | Politeness | Cadence            | Coalescing        | Notes                              |
| ---------------- | ---------- | ------------------ | ----------------- | ---------------------------------- |
| bid / ask sizes  | none       | silent under focus | latest value only | never announced per tick (R-5)     |
| own-order clause | none       | silent             | latest value only | fills are the shell's announcement |

### Density

Row heights from `16`:129 (compact, 24 px) and `16`:130 (comfortable, 32 px), the values of `space.row.height.*` at `9b77e6b83`; both are minimums that grow with the text scale (R-7).

| Mode        | Row / control height                   | Padding tokens                 | Smallest target                                                         |
| ----------- | -------------------------------------- | ------------------------------ | ----------------------------------------------------------------------- |
| compact     | 24 px (`space.row.height.compact`)     | the entry's Tokens field (A-5) | 24 × 24 px (the row; the menu items are CMP-041's, at least 24 px high) |
| comfortable | 32 px (`space.row.height.comfortable`) | the entry's Tokens field (A-5) | 32 × 32 px                                                              |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-111 HeatmapCell (E21-D04, #504)

- [ ] **Final Penpot link** — page `E21-D04`, board 03 (the reveal) — PR 3
- [x] **Variants × States matrix** — table 1; A-9, A-13
- [x] **Keyboard table** — table 2; A-10
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — table 5
- [x] **Motion pair** — N/A — the reveal opens in one frame; the layer's decay is E21-D05 #505's
- [x] **Density notes** — the reveal's table follows CMP-049's densities
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to A-11 after PR 2
- [x] **Data contract confirmed** — the logical unit `{time, price, intensity, side}`; the layer's pipeline is CMP-193's (pack §6)
- [x] **Contrast and CVD** — computed (pack §5.2, §5.3)
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3
- [ ] **Sign-off** — owner `approved` on #504 (pending, #2701)

### Table 1 — Variants × States

| Variant          | State         | Penpot variant                                         | Story name            | Notes                  |
| ---------------- | ------------- | ------------------------------------------------------ | --------------------- | ---------------------- |
| standard palette | reveal closed | CMP-111 · HeatmapCell / Palette=Standard, State=Closed | LowDensity            | a static frame         |
| standard palette | reveal open   | CMP-111 · HeatmapCell / Palette=Standard, State=Open   | RevealOpen            | W-14                   |
| any              | empty history | CMP-111 · HeatmapCell / State=Empty                    | RevealEmptyHistory    | W-15                   |
| any              | pulled        | CMP-111 · HeatmapCell / State=Pulled                   | RevealPulledEstimated | W-16; CMP-227 `inline` |
| any              | stale         | CMP-111 · HeatmapCell / State=Stale                    | RevealStale           | the word "stale"       |
| inverted         | reveal closed | CMP-111 · HeatmapCell / Convention=Inverted            | ConventionInverted    | —                      |
| CVD palette      | reveal closed | CMP-111 · HeatmapCell / Palette=Cvd                    | PaletteCvd            | blue / orange          |

### Table 2 — Keyboard

| Key                          | Action                                                       | Focus after                                                                                                           | Global conflict? | Notes                                                             |
| ---------------------------- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- | ---------------- | ----------------------------------------------------------------- |
| `Shift+Enter` (a ladder row) | opens the reveal for the price                               | the region's heading                                                                                                  | PROPOSED (OQ-1)  | E21-D06 rules it                                                  |
| `Enter` (the pane's stop)    | opens the reveal for the grid row                            | the region's heading                                                                                                  | none             | D02 §9.1                                                          |
| `Tab`                        | heading → the table → the ladder grid; the region stays open | the next stop                                                                                                         | none             | non-modal (PROPOSED); the ladder keeps its tab stop on the opener |
| `Esc`                        | closes the reveal (from anywhere in it)                      | the opener; if virtualised away or re-centred, the rendered row at its price, else the nearest by price; never `body` | none             | re-read = `Esc`, then reopen                                      |

### Table 3 — Accessible name / role

| Element    | Role   | Accessible name (source) | States / properties                             |
| ---------- | ------ | ------------------------ | ----------------------------------------------- |
| the reveal | region | W-14                     | a heading with `tabindex="-1"`                  |
| sparkline  | img    | W-24 (CMP-024)           | bid solid, ask dashed, each labelled at its end |
| the table  | table  | W-25 (CMP-049)           | the W-17 line; a snapshot, not live             |

### Table 5 — Live data

| Field            | Politeness | Cadence                               | Coalescing | Notes                              |
| ---------------- | ---------- | ------------------------------------- | ---------- | ---------------------------------- |
| the reveal table | none       | on open (re-read: `Esc`, then reopen) | snapshot   | nothing announced per update (R-5) |

### Density

| Mode        | Row / control height  | Padding tokens | Smallest target |
| ----------- | --------------------- | -------------- | --------------- |
| compact     | CMP-049's compact row | CMP-049's      | 24 × 24 px      |
| comfortable | CMP-049's comfortable | CMP-049's      | 32 × 32 px      |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-113 HeatmapLegend (E21-D04, #504)

- [ ] **Final Penpot link** — page `E21-D04`, boards 04, 05 and 09 — PR 3
- [x] **Variants × States matrix** — table 1; A-16, A-21
- [x] **Keyboard table** — N/A — static, no interactive element
- [x] **Accessible name / role table** — table 3; A-17
- [x] **Live data** — table 5
- [x] **Motion pair** — N/A — none animated
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to A-18 after PR 2
- [x] **Data contract confirmed** — props only; the anchors and scale from E21-T06 #651 (A-20; G-2)
- [x] **Contrast and CVD** — computed (pack §5.2, §5.3)
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3
- [ ] **Sign-off** — owner `approved` on #504 (pending, #2701)

### Table 1 — Variants × States

| Variant                     | State   | Penpot variant                                                  | Story name            | Notes                               |
| --------------------------- | ------- | --------------------------------------------------------------- | --------------------- | ----------------------------------- |
| standard, green-bid-red-ask | default | CMP-113 · HeatmapLegend / Palette=Standard, Convention=Default  | Default               | W-10, W-11, W-12                    |
| standard, red-bid-green-ask | default | CMP-113 · HeatmapLegend / Palette=Standard, Convention=Inverted | AlternateConvention   | colour words swapped                |
| CVD                         | default | CMP-113 · HeatmapLegend / Palette=Cvd, Convention=Default       | PaletteCvd            | blue / orange                       |
| CVD, inverted               | default | CMP-113 · HeatmapLegend / Palette=Cvd, Convention=Inverted      | PaletteCvdInverted    | —                                   |
| log / linear                | default | CMP-113 · HeatmapLegend / Scale=Log                             | LogScale, LinearScale | W-13                                |
| adaptive / locked           | default | CMP-113 · HeatmapLegend / Mode=Adaptive                         | Adaptive, Locked      | W-13                                |
| any                         | stale   | CMP-113 · HeatmapLegend / State=Stale                           | Stale                 | —                                   |
| any                         | no data | CMP-113 · HeatmapLegend / State=NoData                          | NoData                | anchors "—" and the words "no data" |
| any                         | forced  | —                                                               | ForcedColors          | pack §5.5                           |

### Table 3 — Accessible name / role

| Element      | Role      | Accessible name (source)            | States / properties |
| ------------ | --------- | ----------------------------------- | ------------------- |
| the legend   | group     | "Heatmap legend" plus the sentence  | static              |
| a swatch row | CMP-037's | the side words and the anchor value | —                   |

### Table 5 — Live data

| Field   | Politeness | Cadence | Coalescing        | Notes                 |
| ------- | ---------- | ------- | ----------------- | --------------------- |
| anchors | none       | silent  | latest value only | never announced (R-5) |

### Density

| Mode        | Row / control height | Padding tokens | Smallest target |
| ----------- | -------------------- | -------------- | --------------- |
| compact     | CMP-037's row        | CMP-037's      | N/A — static    |
| comfortable | CMP-037's row        | CMP-037's      | N/A — static    |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-227 EstimatedBadge (E21-D04, #504)

- [ ] **Final Penpot link** — page `E21-D04`, board 07 — PR 3
- [x] **Variants × States matrix** — table 1 (usage only; the contract is E25-D05's, #619); A-23
- [x] **Keyboard table** — the entry's (`15`:2937); nothing added
- [x] **Accessible name / role table** — the entry's; nothing added
- [x] **Live data** — N/A — static badge
- [x] **Motion pair** — N/A — the entry's
- [x] **Density notes** — the entry's sizes `sm` / `md`
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — the entry's Tokens field, unchanged
- [x] **Data contract confirmed** — the entry's (`15`:2941), unchanged
- [x] **Contrast and CVD** — the entry's measured word; no new pair
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3
- [ ] **Sign-off** — owner `approved` on #504 (pending, #2701)

### Table 1 — Variants × States

| Variant  | State   | Penpot variant                                         | Story name | Notes                                  |
| -------- | ------- | ------------------------------------------------------ | ---------- | -------------------------------------- |
| `inline` | default | CMP-227 · EstimatedBadge / Variant=Inline, Host=Strip  | Inline     | detector strip; the queue estimate W-8 |
| `marker` | default | CMP-227 · EstimatedBadge / Variant=Marker, Host=Pulled | Marker     | the pulled mark (M AD-6)               |

## Handoff checklist — CMP-228 PreviewTile (E21-D04, #504)

- [ ] **Final Penpot link** — page `E21-D04`, board 08 — PR 3
- [x] **Variants × States matrix** — table 1 (the `heatmap` kind); A-24
- [x] **Keyboard table** — N/A — not interactive (`role="img"`)
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — N/A — sample data only
- [x] **Motion pair** — N/A — none (the entry: a recomputing tile keeps its last frame)
- [x] **Density notes** — the entry's
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — the entry's Tokens field plus the active palette's stops
- [x] **Data contract confirmed** — a seeded synthetic book; never live or recorded data
- [x] **Contrast and CVD** — the palette sets of pack §5.2, §5.3
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3
- [ ] **Sign-off** — owner `approved` on #504 (pending, #2701)

### Table 1 — Variants × States

| Variant             | State  | Penpot variant                                       | Story name      | Notes                  |
| ------------------- | ------ | ---------------------------------------------------- | --------------- | ---------------------- |
| `heatmap`, standard | sample | CMP-228 · PreviewTile / Kind=Heatmap, State=Sample   | Heatmap         | W-18                   |
| `heatmap`, CVD      | sample | CMP-228 · PreviewTile / Kind=Heatmap, Palette=Cvd    | HeatmapCvd      | added as a Table 1 row |
| `heatmap`, inverted | sample | CMP-228 · PreviewTile / Kind=Heatmap, Convention=Inv | HeatmapInverted | added as a Table 1 row |
| `heatmap`           | empty  | CMP-228 · PreviewTile / Kind=Heatmap, State=Empty    | Empty           | "Preview unavailable"  |
| `heatmap`           | error  | CMP-228 · PreviewTile / Kind=Heatmap, State=Error    | Error           | "Preview unavailable"  |

### Table 3 — Accessible name / role

| Element  | Role | Accessible name (source)                                        | States / properties                   |
| -------- | ---- | --------------------------------------------------------------- | ------------------------------------- |
| the tile | img  | W-18's template, filled from the settings (words, one sentence) | never the only disclosure (`15`:2949) |

## Handoff checklist — CMP-229 ArmToggle (E21-D04, #504)

- [ ] **Final Penpot link** — page `E21-D04`, board 07 — PR 3
- [x] **Variants × States matrix** — table 1 (usage only; the contract is E30-D04's, #917); A-25
- [x] **Keyboard table** — table 2
- [x] **Accessible name / role table** — the entry's (`15`:2964); nothing added
- [x] **Live data** — the entry's countdown; nothing added
- [x] **Motion pair** — N/A — the entry's
- [x] **Density notes** — the entry's
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — the entry's plus R-3's T2 tokens
- [x] **Data contract confirmed** — the entry's (`15`:2967), unchanged
- [x] **Contrast and CVD** — pack §5.4 (the T2 label and reason on `color.surface.raised`)
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3
- [ ] **Sign-off** — owner `approved` on #504 (pending, #2701)

### Table 1 — Variants × States

| Variant     | State        | Penpot variant                                    | Story name           | Notes                                      |
| ----------- | ------------ | ------------------------------------------------- | -------------------- | ------------------------------------------ |
| `scope` dom | read-only T2 | CMP-229 · ArmToggle / Scope=Dom, State=ReadOnlyT2 | ReadOnlyT2, ScopeDom | W-19 + W-20; R-3; never `opacity.disabled` |

### Table 2 — Keyboard

| Key                                  | Action                         | Focus after | Global conflict?                                                                                                  | Notes                                    |
| ------------------------------------ | ------------------------------ | ----------- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| `Enter` / `Space` (the focused pill) | re-shows W-20; changes nothing | stays       | none                                                                                                              | R-3 (G-T2.3); the path that always works |
| `Ctrl+Shift+T`                       | re-shows W-20; changes nothing | stays       | the arm key (`14`:1214; D02:384); `05` §3.2 says `Ctrl+Shift+1`; the web build's browser can take it (D06E14:646) | R-3 (G-T2.3)                             |

## Handoff checklist — CMP-230 OwnOrderMarker (E21-D04, #504)

- [ ] **Final Penpot link** — page `E21-D04`, boards 06 and 09 — PR 3
- [x] **Variants × States matrix** — table 1; A-28, A-32
- [x] **Keyboard table** — table 2; A-29
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — table 5
- [x] **Motion pair** — N/A — none animated (pending and amending are words)
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to A-30 after PR 2
- [x] **Data contract confirmed** — props only, already filtered by an account-scoped caller (A-31; pack §8)
- [x] **Contrast and CVD** — text in `color.text.primary` / `.secondary`, the side word in `color.buy.default` / `color.sell.default`, all on the canvas (pack §5.4); no new pair
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3
- [ ] **Sign-off** — owner `approved` on #504 (pending, #2701)

### Table 1 — Variants × States

| Variant            | State       | Penpot variant                                            | Story name             | Notes                   |
| ------------------ | ----------- | --------------------------------------------------------- | ---------------------- | ----------------------- |
| single             | working     | CMP-230 · OwnOrderMarker / Variant=Single, State=Working  | SingleOrder            | W-2                     |
| single             | pending     | CMP-230 · OwnOrderMarker / Variant=Single, State=Pending  | Pending                | W-6                     |
| single             | amending    | CMP-230 · OwnOrderMarker / Variant=Single, State=Amending | Amending               | W-7                     |
| aggregate          | collapsed   | CMP-230 · OwnOrderMarker / Variant=Aggregate              | GroupAggregate         | W-3                     |
| aggregate          | mixed sides | CMP-230 · OwnOrderMarker / Variant=Aggregate, Sides=Mixed | MixedSides             | W-4                     |
| aggregate expanded | expanded    | CMP-230 · OwnOrderMarker / Variant=Aggregate, State=Open  | GroupAggregateExpanded | W-5; synthetic accounts |
| position marker    | default     | CMP-230 · OwnOrderMarker / Variant=Position               | PositionMarker         | W-9                     |
| any                | drag T2     | CMP-230 · OwnOrderMarker / State=DragT2                   | DragT2                 | R-3                     |

### Table 2 — Keyboard

| Key      | Action                                                                                      | Focus after           | Global conflict? | Notes                                                                   |
| -------- | ------------------------------------------------------------------------------------------- | --------------------- | ---------------- | ----------------------------------------------------------------------- |
| `Enter`  | expands an aggregate                                                                        | the first account row | none             | D02:340                                                                 |
| `Esc`    | collapses it                                                                                | back to the cell      | none             | —                                                                       |
| `Delete` | cancels a single order or the focused account row's order; on an aggregate cell, expands it | stays                 | none             | never cancels all; W-21 … W-23 once (R-5); never gated on the arm (R-4) |

### Table 3 — Accessible name / role

| Element        | Role     | Accessible name (source)      | States / properties         |
| -------------- | -------- | ----------------------------- | --------------------------- |
| the cell       | gridcell | W-2, or W-3 / W-4 (aggregate) | `aria-expanded` (aggregate) |
| an account row | row      | W-5                           | —                           |

### Table 5 — Live data

| Field              | Politeness | Cadence         | Coalescing            | Notes                                                          |
| ------------------ | ---------- | --------------- | --------------------- | -------------------------------------------------------------- |
| status (pending …) | none       | silent          | latest value only     | the word changes; never announced (R-5)                        |
| cancel result      | polite     | once per cancel | the latest within 5 s | W-21, then W-22 or W-23, through the panel's status node (R-5) |

### Density

Row heights are CMP-108's: `16`:129 (compact, 24 px) and `16`:130 (comfortable, 32 px) at `9b77e6b83`.

| Mode        | Row / control height   | Padding tokens | Smallest target                                                                              |
| ----------- | ---------------------- | -------------- | -------------------------------------------------------------------------------------------- |
| compact     | 24 px (the ladder row) | CMP-108's      | 24 × 24 px: the count badge's expand target is the whole cell, never the badge alone (2.5.8) |
| comfortable | 32 px (the ladder row) | CMP-108's      | 32 × 32 px                                                                                   |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |
