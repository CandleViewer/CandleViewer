# E15-D11 — Hand-off: SCR-049 multi-chart grid (`16` §11.4; CMP-253 MultiChartGrid)

One new entry, **CMP-253 MultiChartGrid**, and the rows on CMP-196, CMP-217 and CMP-218. The rules are the spec ([`docs/design/specs/e15-multichart-grid.md`](../specs/e15-multichart-grid.md)); the decisions, the measurements and §C are the pack ([E15-D11.md](E15-D11.md)); every "§" below without a prefix is the pack's. This file never restates a props table (C-16.5); every number is the tool's (`docs/design/_tools/e15_d11_grid_audit.py`).

## 1. Read me first

Builders read the spec first. The builder of record is E15-S06 (#559); its entry condition is the multi-chart reading E15-K01 (#371) owes (§13, #2701 ledger addendum A row A45). Nothing here is storage-settled: every frame that saves or restores a grid is "storage pending" until the contract adds the grid's pane kind (§14, G-1).

**Safety (C-2.6; spec §8).** LOCKED covers order entry and arming only: cancel, close, flatten and setting or tightening a stop are never gated, hidden or blocked by the grid or by any cell's state, maximised or not (they live on the positions and orders surfaces, and their own hotkeys keep working in every grid state). A non-maximised cell never arms (A44); a maximised cell shows CMP-229's arm state in its row; restoring while armed shows "Disarming chart trading…" until the server answers, and a failed disarm keeps the armed state visible with [Disarm].

## 2. Hand-off checklist (E15-D11, #365) — CMP-253 and the rows it touches

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason (`16` §11.4, §13.3).

| Item                     | CMP-253 MultiChartGrid                                                   | CMP-217 `cell` mode       | CMP-218 for new cells          | CMP-196                      |
| ------------------------ | ------------------------------------------------------------------------ | ------------------------- | ------------------------------ | ---------------------------- |
| Final Penpot link        | [ ] PR 3, file `E15-D11 boards`, page `E15-D11 multi-chart grid`         | [ ] PR 3                  | [ ] PR 3                       | [ ] N/A — non-visual         |
| Variants × states        | [x] A-8; spec §3, §4, §10, §11                                           | [x] A-13 … A-15; spec §3  | [x] A-16, A-17; spec §9        | [x] A-12                     |
| Keyboard table           | [x] §4 below                                                             | [x] §4 below (the menu's) | [x] E15-D06's, unchanged       | [ ] N/A — non-visual         |
| Accessible name and role | [x] §3 below                                                             | [x] §3 below              | [x] §3 below                   | [x] the shared status region |
| Live data                | [x] polite, once per event; a failed disarm assertive; no crosshair      | [x] none                  | [x] once per membership change | [x] once per state change    |
| Motion pair              | [x] A-8's Motion spec (cuts); the timings E15-D14's                      | [x] none                  | [x] none                       | [ ] N/A                      |
| Density notes            | [x] §6 below; pack §5                                                    | [x] CMP-041's             | [x] E15-D13's                  | [ ] N/A                      |
| Essential exceptions     | [x] none                                                                 | [x] none                  | [x] none                       | [x] none                     |
| Tokens used              | [x] §6 below; pack §16                                                   | [x] E15-D13 A-54          | [x] E15-D13 A-58               | [ ] N/A                      |
| Data contract            | [ ] G-1, storage pending                                                 | [x] none new              | [x] none new                   | [x] none new                 |
| Contrast and CVD         | [x] pack §6                                                              | [x] CMP-041's             | [x] pack §6 (P-4 … P-6)        | [ ] N/A                      |
| Storybook                | [x] §5 below                                                             | [x] §5 below              | [x] §5 below                   | [x] `ChartEngine/*`, as is   |
| Sign-off                 | [ ] the orchestrator's design approval (BQ-22); SCR-049's withheld (A45) | [ ] as CMP-253            | [ ] as CMP-253                 | [ ] as CMP-253               |

## 3. Names and descriptions

Names fixed at every width, step and zoom; the interval spelled; the sync group in the description, never the name (E15-D15 R-5; pack §7); each description in the spec §6's order.

| Element                           | Role     | Name                                                  | Description                                                                                                                                                      |
| --------------------------------- | -------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| the grid                          | `region` | "Chart grid, 2 by 2, Live"                            | "4 charts. New charts join sync group A."                                                                                                                        |
| a cell                            | `region` | "Chart, BTCUSDT 4 hours, Live"                        | "Chart 1 of 4. Sync group A: symbol and crosshair. Feed: Live; mark 64,011.5; last 64,011.0. Chart trading locked (entry only): Maximise this chart to trade."   |
| a demo cell                       | `region` | "Chart, ETHUSDT 1 hour, Demo"                         | "Chart 2 of 4. Sync group B: interval and crosshair. Feed: Live; mark 3,412.25; last 3,412.20. Chart trading locked (entry only): Maximise this chart to trade." |
| an empty cell                     | `region` | "Empty chart cell, 3 of 4"                            | "Add a chart to this grid cell." (no chart, so no arm state to state)                                                                                            |
| the arrangement button            | `button` | "Grid arrangement, 2 by 2"                            | "Opens the arrangements."                                                                                                                                        |
| the grid's sync button            | `button` | "Sync for new charts, group A"                        | "Each chart follows its own sync group."                                                                                                                         |
| the symbol picker                 | `button` | "Symbol, BTCUSDT"                                     | —                                                                                                                                                                |
| the interval picker               | `button` | "Interval, 4 hours"                                   | —                                                                                                                                                                |
| the sync badge                    | `button` | "Sync group A"                                        | "Symbol and crosshair. Opens the sync menu."                                                                                                                     |
| the environment badge             | text     | "Live"                                                | —                                                                                                                                                                |
| the cell menu                     | `button` | "Chart menu, BTCUSDT 4 hours"                         | —                                                                                                                                                                |
| a switcher tab                    | `tab`    | "Chart 1, BTCUSDT 4 hours, Live"                      | "Sync group A."                                                                                                                                                  |
| the Restore button                | `button` | "Restore grid"                                        | —                                                                                                                                                                |
| the arm control (maximised cell)  | `button` | "Chart trading: locked" (CMP-229; "armed" when armed) | the time left (CMP-035), never in the name                                                                                                                       |
| the Disarm button (disarm failed) | `button` | "Disarm chart trading, chart 3"                       | "Chart trading is still armed on chart 3."                                                                                                                       |
| the Reduced chip                  | `button` | "Reduced detail"                                      | the reductions in words (spec CP-27)                                                                                                                             |

## 4. Keyboard

| Keys                                  | Scope                            | Does                                                                                                                                      | Status                                                  |
| ------------------------------------- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| `Ctrl+Alt+1..9`                       | the grid or a cell               | focuses cell N; past the arrangement says "This grid has 4 charts."                                                                       | PROPOSED (KB-15; OQ-1 the `AltGr` caveat)               |
| `Ctrl+Alt+Enter`                      | the grid or a cell               | maximises the active cell; again restores                                                                                                 | PROPOSED (OQ-2)                                         |
| `Esc`                                 | anywhere                         | closes a menu or the confirm; never restores                                                                                              | `05`'s universal cancel                                 |
| `Ctrl+Alt+←` / `Ctrl+Alt+→`, `Ctrl+\` | the workspace                    | stop at the grid once, on its active cell                                                                                                 | shipped                                                 |
| `F11`                                 | the grid as a panel              | maximises the grid in the dock; again restores                                                                                            | shipped (E15-D04)                                       |
| `Tab` / `Shift+Tab`                   | the workspace                    | one stop for the grid, on its active cell; inside a cell (after `Enter`) the row's controls, then the chart surface, then out of the grid | `05`:95's roving tabindex; the engine's model unchanged |
| arrows, `Home`, `End`                 | a cell (the cell itself focused) | move to the neighbouring cell; `Home` / `End` the first and the last                                                                      | `05`:95's roving tabindex                               |
| `Enter`                               | a cell (the cell itself focused) | goes into the cell's row controls                                                                                                         | PROPOSED (with KB-15)                                   |
| `Shift+F10` or the context-menu key   | a cell                           | opens the cell menu (Maximise chart, Change symbol…, Sync group ▸, Move chart ▸, Focus chart ▸, Remove chart)                             | E15-D15's menu rule                                     |
| arrows, `Home`, `End`                 | the switcher tablist             | move between cells (one shown at a time)                                                                                                  | CMP-042's                                               |
| E15-D04's splitter keys               | a custom grid's divider          | move the divider                                                                                                                          | CMP-083's                                               |

## 5. Stories

| Component | Tree                            | Stories (each in dark / light × compact / comfortable)                                                                                                                                                                                                                            | Builder        |
| --------- | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| CMP-253   | `Organisms/Dock/MultiChartGrid` | OneByTwo, TwoByTwo, ThreeByThree, OnePlusThree, Custom, ActiveCell, NarrowSteps, Switcher, Zoom200, Maximised, EmptyCell, LoadingCell, UnavailableCell, DelistedCell, ShortHistory, BudgetConfirm, BudgetRunning, Reduced, TradingLocked, MaximisedArmed, Disarming, DisarmFailed | E15-S06 (#559) |
| CMP-217   | `Molecules/LayoutPresetMenu`    | CellMode, CellModeShrinkConfirm                                                                                                                                                                                                                                                   | E15-S01 (#401) |
| CMP-218   | `Molecules/SyncMenu`            | GridNewCells                                                                                                                                                                                                                                                                      | E15-S04 (#477) |

## 6. Redlines and the cell row's DOM budget

| Element                   | Token                                                  | Value                                                                        |
| ------------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------------- |
| the grid frame            | `border.panel.focus` (CMP-080, E15-D03 D-1)            | 2<!--=BUDGET:frame--> px a side, in both states                              |
| the grid header           | `space.panelheader.height.*` on `color.surface.raised` | 24<!--=BUDGET:row.compact--> / 32<!--=BUDGET:row.comfortable--> px           |
| a cell row                | `space.panelheader.height.*` on `color.surface.canvas` | 24<!--=BUDGET:row.compact--> / 32<!--=BUDGET:row.comfortable--> px           |
| the divider between cells | `border.hairline` in `color.border.default`            | 1<!--=BUDGET:divider--> px                                                   |
| the active-cell marker    | `border.thick` in `color.text.primary` / `.secondary`  | 2<!--=BUDGET:marker--> px, inside the row's bottom edge                      |
| the cell row's minimum    | measured (pack §5)                                     | 268<!--=BUDGET:hdr.min.compact--> / 292<!--=BUDGET:hdr.min.comfortable--> px |
| the cell's height minimum | `size.row.*` × 4 + the row + the time strip            | 144<!--=BUDGET:minh.compact--> / 192<!--=BUDGET:minh.comfortable--> px       |

The cell row at its fullest, counted (the tool's anatomy; BQ-08's budget is 24<!--=BUDGET:node.budget--> nodes and 7<!--=BUDGET:interactive.budget--> interactive elements): 18<!--=BUDGET:nodes--> nodes, 4<!--=BUDGET:interactive--> interactive; a maximised cell's row adds the arm state: 22<!--=BUDGET:nodes.max--> nodes, 5<!--=BUDGET:interactive.max--> interactive.

| Part                                                                    | Nodes | Interactive |
| ----------------------------------------------------------------------- | ----- | ----------- |
| the row (no role; the marker is its bottom border)                      | 1     | 0           |
| the cell number                                                         | 1     | 0           |
| the symbol picker: button, label, caret                                 | 3     | 1           |
| the interval picker: button, label, caret                               | 3     | 1           |
| the sync badge: button, tile, letter, glyph, words                      | 5     | 1           |
| the environment badge (CMP-075): container, word, glyph                 | 3     | 0           |
| the cell menu: button, glyph                                            | 2     | 1           |
| maximised only: the arm state (CMP-229): button, glyph, word, countdown | 4     | 1           |

## 7. The single chrome layer: the recommendation and its sign-off (T:75; BQ-08)

**Recommendation.** Render every cell row of a grid as **one chrome layer**: one component instance that lays out up to nine rows from the grid's geometry, static between binding changes, never re-rendered on a chart frame, rather than nine independent React subtrees. **The reason:** cell chrome is multiplied by up to nine, and the rule is that chrome never repaints with the chart (spec §12 rule 1); one layer makes that true by construction and keeps the node count at nine times one row. **It is a recommendation:** the builder may meet the same budget another way; the budget (24<!--=BUDGET:node.budget--> nodes and 7<!--=BUDGET:interactive.budget--> interactive elements a row, no repaint on a chart frame) binds. **Sign-off:** "the FE lead" is E15-S06's builder, confirming it at the hand-off review on #559; the orchestrator's design approval records it under the delegation.

## 8. Hand-off rows

| To             | What                                                                                                                            |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| E15-S06 (#559) | the grid; the C-rows routed to it (C-4, C-10, C-11, C-12, C-14); G-1 with the contract's owner; G-3                             |
| E15-K01 (#371) | the multi-chart reading, the entry condition of the build (A45); the threshold the prompt cites (OQ-3)                          |
| E11            | the rendering model (C-16); US-CHART-011's overlay and ratio (C-19)                                                             |
| E15-D13 (#367) | PR 1 (#5055), PR 2 (#5073) and PR 2T (#5075, `18d92caf3f`) merged; the dock tokens are in the base; PR 3 binds them             |
| E15-D12 (#366) | its PR 1 is #5071 (open); its PR 2 lands first; its vocabulary is cited in pack §12, re-pinned by content at this ticket's PR 2 |
| E15-D14        | the maximise and switcher timings (OQ-4)                                                                                        |
