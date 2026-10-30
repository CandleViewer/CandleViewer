# E15 multi-chart grid (SCR-049): the normative spec

**Owner:** E15-D11 (#365) · **Status:** Draft, PR 1 of 3 (`Refs #365`). This is the page a builder reads: the rules for SCR-049, the multi-chart grid panel, each stated once. The decisions, the measurements, the inbound ledger and the conflicts are in [E15-D11.md](../E15/E15-D11.md) (the pack); the checklists and the keyboard, name, story and redline tables are in [E15-D11-handoff.md](../E15/E15-D11-handoff.md). Every pixel figure here is computed by `docs/design/_tools/e15_d11_grid_audit.py` from the tokens and E15-D03's budget. The builder is E15-S06 (#559); a build never starts on SCR-049 without the multi-chart reading (the pack §13).

## 1. Scope and reading

SCR-049 is **one dock panel holding 2 to 9 chart cells** under one shared header. A cell is not a panel: it is never docked, floated, popped out or stored as a pane. Out of scope here, as the ticket says: the chart rendering (E11 / E12), the sync engine CMP-196 and its configuration surface (E15-D06), workspace docking (E15-D04) and motion (E15-D14). The grid's catalogue entry is CMP-253 MultiChartGrid (the pack §15). Words: **grid** = the SCR-049 panel; **cell** = one chart inside it; **active cell** = the cell the grid's commands act on; **grid header** = the panel's one CMP-082 row; **cell row** = a cell's own header row.

## 2. The distinguishing cue: one panel, not four

A user tells a grid from four docked charts by three cues, each a rule; at least two are non-hue and hold in every theme and density (compact, comfortable and the chart's `dense`):

1. **One frame, no gutter.** The grid has CMP-080's one frame and focus reservation (2<!--=BUDGET:frame--> px a side, `border.panel.focus`). Inside it the cells meet at a `border.hairline` divider (1<!--=BUDGET:divider--> px) in `color.border.default` on `color.surface.canvas`, never the dock's `space.dockgrid.gutter` (4<!--=BUDGET:gutter--> px) on `color.surface.app` and never a splitter hit band. The one exception is a custom grid's own divider (§3).
2. **One header, light cell rows.** One CMP-082 grid header on `color.surface.raised` carries the grid glyph and "Grid · 2×2 ▾"; each cell row sits on `color.surface.canvas`, with no move handle, no × and a cell menu only.
3. **Only the grid moves.** The grid carries the one move handle, × and Pop out; a cell carries no dock affordance (no grip, no drop zones, no Pop out, no float).

## 3. Arrangements

- **The five.** 1×2, 2×2, 3×3, 1+3 (the large cell left at 0.6<!--=BUDGET:large--> of the width, three equal rows right) and **Custom: rows × columns**, a 3 × 3 chooser of equal cells: any 1 to 3 rows by 1 to 3 columns holding 2 to 9 cells, so the stacked 2 × 1 and 3 × 1 and the side-by-side 1 × 3 are allowed. The ruled bound is the cell count (2 to 9), not the orientation; stacked rows share one time axis, the common multi-timeframe read; the dock's "3×1" exclusion (`15`:2784) is the dock's preset list, not a grid's custom shape. Only 1 × 1 is refused, as one chart is a chart panel. A custom grid alone has one resizable divider per axis: a CMP-083 separator with E15-D04's splitter keys. A custom divider stops where a neighbouring cell would go below the cell minimum (§4), as a dock splitter stops at a panel's minimum (`D04`:234, "which a splitter can never cause (it stops first, §6)"), so a divider never brings the fallback on; only the slot, the window or the zoom can. No cell is dragged, and no cell is dragged out.
- **The chooser.** The grid header's "Grid · 2×2 ▾" opens CMP-217 in its `cell` mode: a list of thumbnails whose names are words ("Two by two, four charts"), never the dock's preset gallery, so the two choices never share a list.
- **Bounds.** At least 2 cells and at most 9; the grid counts as one pane against the layout's 16.
- **Changing it.** Growing adds empty cells. Shrinking that would remove bound cells asks first in a CMP-044 confirm naming the charts that go, Cancel focused; nothing changes until the user chooses. A shrink that removes only empty cells applies at once.
- **Reading order.** Left to right, top to bottom; it numbers the cells 1 to 9.

## 4. The cell row

- **Anatomy, in order.** Cell number (`type.ui.caption`, `color.text.secondary`) · symbol ▾ · interval ▾ · the sync badge (E15-D06 D-1) · the environment badge (CMP-075) · the cell menu ⋮. One row at `space.panelheader.height.compact` / `.comfortable` (24<!--=BUDGET:row.compact--> / 32<!--=BUDGET:row.comfortable--> px) on `color.surface.canvas`; insets `space.2` at the left and right ends; the elements centred in the row's height, which is the token, with no top or bottom inset; gaps `space.2` compact and `space.3` comfortable. No status row: the feed, mark and last move to the cell menu's status line and the cell's description; the environment is in the row.
- **The two badges, quoted.** The sync badge is E15-D06 D-1's (`D06`:118): "a button styled as a chip", the letter tile, the `link` glyph, then "the shared axes in words"; at step 2 "the words become a count" ("A · 2"); at step 4 the letter only; named "Sync group A" at every step. A cell in no group shows D-1's other form: "No sync" is "the `unlink` glyph and the words, no tile". The environment badge is E15-D03 D-4's (`D03`:169): "CMP-075 with E10-D03 §1.2's four channels (word, weight, glyph, `border.thick` `color.env.*` rule) and LIVE's `border.thick` underline".
- **Disclosure order** (E15-D03 D-3's steps, one level down), as the cell narrows:
  1. the cell number goes (it stays in the cell's description, its menu and the `Ctrl+Alt+N` hint);
  2. the sync badge's axes words become a count;
  3. the symbol and interval pickers drop their carets (each stays a button);
  4. the sync badge shows its letter only (its name stays "Sync group A").
- **Where each step fires** (the cell's width, from the tool): a cell draws the first row that fits it. The full row needs 442<!--=BUDGET:hdr.s0.compact--> px compact and 470<!--=BUDGET:hdr.s0.comfortable--> px comfortable; narrower, step 1 needs 426<!--=BUDGET:hdr.s1.compact--> / 450<!--=BUDGET:hdr.s1.comfortable-->; narrower, step 2 needs 326<!--=BUDGET:hdr.s2.compact--> / 350<!--=BUDGET:hdr.s2.comfortable-->; narrower, step 3 needs 294<!--=BUDGET:hdr.s3.compact--> / 318<!--=BUDGET:hdr.s3.comfortable-->; narrower, step 4 needs 268<!--=BUDGET:hdr.s4.compact--> / 292<!--=BUDGET:hdr.s4.comfortable-->, the minimum; narrower still, the fallback.
- **Never dropped.** The symbol, the interval, the sync letter, the environment badge and the cell menu never drop. The accessible name never changes with width.
- **Minimum.** Step 4 measures 268<!--=BUDGET:hdr.min.compact--> px compact and 292<!--=BUDGET:hdr.min.comfortable--> px comfortable inside the cell, inside its `border.hairline` dividers (a divider belongs to no cell); a cell's height minimum is its row, the time strip and four price rows (`size.row.compact` / `.comfortable`): 144<!--=BUDGET:minh.compact--> / 192<!--=BUDGET:minh.comfortable--> px.
- **The fallback.** When any cell is below either minimum (a narrow slot, a narrow window, 200 % zoom), the grid shows **one cell at a time** with a cell switcher row: a CMP-042 tablist, one tab per cell ("1 · BTCUSDT 4h · A" drawn, "Chart 1, BTCUSDT 4 hours, Live" named), arrows, `Home` and `End`. It is a display transform: the stored arrangement never changes, and widening restores the grid exactly. It is the rule E15-D12 applies to the dock below its minimum, one level down.
- **The fallback's details.** The switcher row is CMP-251's row: `space.panelheader.height.*` with its bottom `border.hairline` (25<!--=BUDGET:switcher.compact--> / 33<!--=BUDGET:switcher.comfortable--> px), under the grid header; the one cell fills the rest of the body. The cell shown first is the active cell (§5), so its tab is the selected one; selecting a tab makes that cell the active cell. In tab view the selected tab is the marker: one cell shows, so its row draws no underline. Nine tabs that do not fit share the row in CMP-251's form, "a long label truncates with its full name in the accessible name" (`15`:3120), cut from the end so the cell number leads; never a scroll and never an overflow menu. A single cell still under either minimum keeps its minimum and the grid's body scrolls to it (the cell scrolls); it never shrinks below it.
- **The measured cases** (the pack §5 computes them). The grid's body is its slot less CMP-080's frame and the grid header, a `space.panelheader.height.*` row (24<!--=BUDGET:row.compact--> / 32<!--=BUDGET:row.comfortable--> px). **The 1280 × 800 dock area** (1168×640<!--=BUDGET:slot.1280.compact--> compact, 1168×632<!--=BUDGET:slot.1280.comfortable--> comfortable), compact: 3×3 cells measure 387×203<!--=BUDGET:case.dock1280.cell--> and draw step 2<!--=BUDGET:case.dock1280.step-->; comfortable 387×198<!--=BUDGET:case.dock1280c.cell-->, step 2<!--=BUDGET:case.dock1280c.step-->. **The Scalping chart column** (698<!--=BUDGET:col.width--> px wide, E15-D03's Scalping workspace at 1280 × 800), compact: 3×3 cells measure 230×203<!--=BUDGET:case.col.cell-->, under the minimum, so the grid shows the switcher<!--=BUDGET:case.col.step-->; its one cell measures 694×587<!--=BUDGET:case.col.one--> and draws step 0<!--=BUDGET:case.col.onestep--> (the full row); comfortable 230×198<!--=BUDGET:case.colc.cell-->, the switcher<!--=BUDGET:case.colc.step-->, one cell 694×563<!--=BUDGET:case.colc.one-->, step 0<!--=BUDGET:case.colc.onestep-->. At 200 % zoom in a 1280×800 window a 2×2 grid's one cell measures 524×187<!--=BUDGET:case.z200.one--> compact (step 0<!--=BUDGET:case.z200.onestep-->) and 524×163<!--=BUDGET:case.z200c.one--> comfortable, under the height minimum, so it scrolls<!--=BUDGET:case.z200c.onestep-->.
- **Budget.** At most 7 interactive elements and 24 DOM nodes per cell row (the hand-off §6 counts them). Cell chrome is static and never repaints with a chart frame.

## 5. The active cell

- E15-D03 D-1 is untouched for the grid as a panel: the inset `border.panel.focus` frame and the header bar in `color.focus.ring`.
- **How a cell becomes active.** A pointer press anywhere in a cell (its row or its chart), focus arriving in the cell or in one of its controls (`Tab`, `Ctrl+Alt+1..9`, the arrow keys between cells, the cell menu's "Focus chart ▸") or the selection of its switcher tab. **On load** the active cell is cell 1 in reading order (§3): the active cell is view state, never stored (§13).
- The active cell is marked by a `border.thick` underline across its header row and its cell number in `font.weight.bold`, never by `color.focus.ring`, a frame round the cell or a change of the cell's box.
- **The marker.** The underline is `border.thick` (2<!--=BUDGET:marker--> px) and runs the row's full width inside its bottom edge, under the controls' boxes and never over a control (the row's height holds both, so no control moves), in `color.text.primary` while the grid or one of its cells has focus and `color.text.secondary` while it has not; the active cell persists, so `Ctrl+Alt+→` back into the grid lands on it. The plot rectangle is the same with and without the marker. At steps 1 to 4 the number is gone and the underline alone marks the cell.
- A control inside a cell keeps CMP-039's focus ring as usual.

## 6. Keyboard, names and announcements

- **Keys.** `Ctrl+Alt+1..9` focuses cell N while the grid or a cell has focus (KB-15, scope `panel`, PROPOSED through the remappable keymap); a number past the arrangement does nothing but say "This grid has 4 charts."; inactive while focus is inside a text input, in `05`'s form for `/` (`05`:47, "Only active when focus is not inside a text input"; PROPOSED, as the shipped keymap has no general text-field guard row). On layouts where `Ctrl+Alt+digit` types a character (`AltGr`), the cell menu's "Focus chart ▸ 1 … 9" is the chord-free path. `Ctrl+Alt+←/→` and `Ctrl+\` stop at the grid once, on its active cell, never at each cell. **One `Tab` stop for the grid** (`05`'s roving tabindex for composite widgets, `05`:95): `Tab` lands on the active cell, the cells' own `tabindex` roving; while a cell itself has focus, the arrow keys move to the neighbouring cell (`Home` / `End` the first and the last), so crossing nine cells costs one `Tab` stop, never one per control. `Enter` goes into the focused cell: `Tab` then runs its row's controls and its chart surface (the engine's keyboard model unchanged, its arrows the chart's), and the next `Tab` leaves the grid; `Shift+Tab` from the row's first control returns to the cell.
- **Names** (E15-D15 R-5, which the cells inherit). The grid: a `region` named "Chart grid, 2 by 2, Live" (kind, arrangement and the environment word when any cell is order-capable). Each cell: a nested `region` named "Chart, BTCUSDT 4 hours, Live". The sync group is in the description, never the name; the interval is spelled.
- **The description, assembled in one order:** "Chart {position} of {count}. Sync group {letter}: {axes}. Feed: {feed}; mark {mark}; last {last}. Chart trading locked (entry only): Maximise this chart to trade." The position; the sync group and its axes (or "No sync."), with the provenance clause ("symbol set by sync group A") after the axes when a change came from the group; the feed, mark and last as the cell menu's status line reads them (CP-32; the feed word is E17-D01's: Live, Delayed, Stale, Resyncing or Disconnected); the arm state (§8; the maximised cell's arm state is CMP-229's); a cell state's own words last ("History from 12 Mar", §10). The copy: "Chart 2 of 4. Sync group A: symbol and crosshair. Feed: Live; mark 64,011.5; last 64,011.0. Chart trading locked (entry only): Maximise this chart to trade." An empty cell is named "Empty chart cell, 3 of 4" and described "Add a chart to this grid cell." (§10).
- **The cell menu, in order:** the status line (not interactive: CP-32, then CP-15), then Maximise chart, Change symbol…, Sync group ▸, Move chart ▸, Focus chart ▸, Remove chart. Its items never change by the arm state (§8).
- **Announced, polite.** Cell focus "{name}, focused"; a grid change once through CMP-081's live region; maximise and restore (§7); a cell's sync membership change once through CMP-196's shared region. A remote crosshair moving in a cell is never announced.

## 7. Maximise and the exact restore

- **How.** The cell menu's "Maximise chart"; `Ctrl+Alt+Enter` toggles it on the active cell (PROPOSED); the grid header's [Restore] while maximised. **`Esc` never restores**: `05` keeps `Esc` as the universal cancel.
- **What shows.** The maximised cell fills the grid's body under the unchanged grid header, which adds "Showing chart 3 of 4" and [Restore]. The grid frame, the TopBar and the StatusBar stay, so the environment is never hidden. The maximised cell's row carries the chart panel's arm control and armed state (§8).
- **Two levels.** `F11` maximises the grid panel in the dock (E15-D04); the cell maximise works inside it; each restores only its own level.
- **Exact restore.** The arrangement, the custom divider positions, every cell's binding, sync group, visible time range, price scale and its mode, and the active cell. The other cells stay mounted while hidden, drawing nothing, and unsubscribe after 30 s, as hidden dock panels do, their viewports kept. Maximise is a view state: never stored, never dirtying the layout.

## 8. The environment and trading in a cell

- Every chart cell carries CMP-075 in its row (environment by kind, E15-D03 D-4), never collapsing, so a cropped, glanced-at or maximised cell names its environment. The crop test runs on one cell.
- **A cell never arms in R1.** Its arm state reads LOCKED, reason "Maximise this chart to trade.", in the cell menu's status line and the cell's description; the row carries no arm control. Trading hotkeys never act on a non-maximised cell. The server holds the arm authority; the design only shows it.
- **Protective actions are never gated** (C-2.6; the arm carve-out, `E30D05`:59, :75). LOCKED covers order entry and arming only: cancel, close, flatten and setting or tightening a stop are never gated, hidden or blocked by the grid or by any cell's state, maximised or not (they live on the positions and orders surfaces, and their own hotkeys keep working in every grid state). A cell in any state still draws its orders, positions and stop lines (E15-D12's never-shed list, §11), and the cell menu never gains or loses an item by the arm state.
- **The maximised cell arms as a chart panel does.** A maximised cell's row carries CMP-229 ArmToggle (`scope: "chart"`) in a chart panel's place, after the environment badge (`D03`:305): LOCKED, ARMED with its `mm:ss` countdown in CMP-229's attention pill (`D03`:323), or UNKNOWN, which fails closed (`15`:2921). The armed pill never leaves the row at any step; as a chart panel's does, its countdown leaves at step 4 and its word becomes its glyph at step 7, both kept in the name and description (`D03`:305). These step numbers are E15-D03 D-3's chart-panel steps, which only this maximised cell's row follows; they are never the four cell-row steps of §4, and a non-maximised cell has no arm pill. The row is then 22<!--=BUDGET:nodes.max--> nodes and 5<!--=BUDGET:interactive.max--> interactive elements, inside the budget (§4).
- **Restore while armed.** [Restore] or `Ctrl+Alt+Enter` returns the grid at once (a view change) and requests the disarm. Until the server answers, the grid header shows "Disarming chart trading…" beside CMP-229's armed pill, which stays visible, and the restored cell's entry stays inert (a non-maximised cell never acts). On the server's answer the pill reads LOCKED and "One-click trading disarmed: chart returned to the grid." is announced once.
- **If the disarm fails** (the server refuses, or the request times out): the header keeps the pill as the server last stated it (ARMED with its countdown, or UNKNOWN, entry off) and a persistent line "Chart trading is still armed on chart 3. Disarm, or maximise it to trade." with [Disarm] (asks again) and [Maximise chart 3]; announced once, assertive, as an arm change is (`15`:2922). The line stays until the server reports LOCKED or the arm expires; the restored cell's entry stays inert throughout, and protective actions stay as above.

## 9. Sync and rebinding

- **The rule:** Each chart follows its own sync group. Every cell is a sync member exactly like a docked chart, and there is no "propagate symbol" toggle: one linking model, not two. The grid header's `Sync ▾` (CMP-218) sets only the group a newly added cell joins and never governs an existing cell; its description is the rule's sentence.
- **Multi-timeframe** is one group with the symbol axis on and the interval axis off: a symbol change in one cell reaches the group's other cells, each keeping its interval.
- **Rebind** by the cell's symbol ▾ and interval ▾ (CMP-219 and the interval picker, as a chart panel's) or the cell menu's "Change symbol…"; the change follows the cell's group exactly as a docked chart's does, the provenance ("set by sync group A") in the description. **Join a group** by the badge (a button) or the cell menu's "Sync group ▸".
- **Add, remove, swap.** An empty cell's [Add chart] opens the symbol picker. "Remove chart" empties the cell with Undo in the toast; the grid's × closes the panel. "Move chart ▸ to cell N" swaps two cells, keyboard first; no drag between cells.

## 10. Cell states

Every state lives inside its cell's box; the row (symbol, interval, badges from the stored document) is always real, and one cell's state never blocks another.

- **Empty:** "Add a chart to this grid cell" and [Add chart]. Its row holds the cell number alone (no chart is bound, so no picker, badge or menu: the never-dropped five are a bound cell's; the marker still draws when it is the active cell); the cell is named "Empty chart cell, 3 of 4" (§6).
- **Loading:** a CMP-015 skeleton body with CMP-038's words; the shimmer stops at 5 s; no spinner over the chart. Under `prefers-reduced-motion: reduce` there is no shimmer: the static two-tone fill from the first frame (E05-D03 row 6's reduce, `E05D03`:74, :90).
- **Unavailable:** "ETHUSDT data unavailable" and [Retry], isolated to the cell.
- **Delisted** (US-LAY-002's partial-restore rule): E15-D03's `error-delisted` one level down, the symbol named, [Change symbol…] and [Remove chart]; the other cells draw normally and the restore line counts it in E15-D12's form.
- **Short history:** the gap drawn as a gap by the engine, a CMP-011 `neutral` chip "History from 12 Mar" (fixture date) and the same words in the description.
- The environment badge waits for the environment to be known, as a panel's does.

## 11. The budget prompt

- **Before applying** an arrangement, or adding a cell, whose estimate crosses the budget: a CMP-044 confirm (E15-D03 D-11), Cancel focused, nothing applied until the user chooses; actions "Use 3×3 with reduced detail", "Use 3×3 anyway", "Cancel". A device that clears the arrangement never sees it.
- **While running** over budget: one line in the grid header, the measurement with its window and target, and "Reduce detail", "Use 2×2", "Keep full detail".
- **The reductions, named and grid-scoped:** charts you aren't using update every 200 ms; heatmap depth one tier lower and footprint numbers hidden in those charts; fewer charts is a separate action. While reduced, the grid header carries a CMP-011 `neutral` "Reduced" chip, its specifics in its name and the grid's description.
- **Shared with E15-D12** (#366, cited, never re-decided): the copy rules (a measurement with its window and target, never a verdict; capabilities, never subsystem words; what still works), the threshold and window (PROPOSED until E15-K01, #371, calibrates them) and the never-shed list (the environment, the arm state, the focused chart, order and position lines, every error state). The device-wide reduced profile stays E15-D12's banner. CMP-227 is not used.

## 12. Performance rules

1. Cell chrome is static and never repaints on a chart frame.
2. The active-cell marker draws inside the cell's existing box: focusing a cell never resizes a viewport.
3. An arrangement change re-lays out viewports and never recreates a rendering context.
4. The prompt names its reductions (§11).
5. Four cells hold ≥ 50 fps inside US-LAY-001's ≥ 55 fps four-pane target.

A cell is a rectangle whose geometry changes never resize a neighbour's; the design depends on no rendering model beyond that (the engine's reading is E11's, the pack C-16).

## 13. Persistence and untrusted text

- **Stored** in the grid pane's `pane_config` ("storage pending" on every frame until the contract lands): the arrangement (or rows × columns and the custom divider positions) and, per cell, its symbol, interval and sync group. The active cell and a maximised cell are view state, never stored.
- **Cells are not panes:** no `layout_panes` row each, no dock id, never floatable. The pane kind and the validated `pane_config` shape (2 to 9 cells, refused with a stated reason on load and on import) are a contract gap for the contract's owner, contract first.
- **Creation:** the panel picker's Charts category gains "Chart grid" (E15-D07's worked placement), drawn storage pending.
- **Symbols** come from saved and imported documents: text only, capped at the contract's 20 characters with an ellipsis and the full value in the name (E15-D09's rule).

## 14. Copy deck

Each string with its id, surface and level (`visible` drawn, `polite` announced, `assertive` announced at once, as an arm change is, `none` a name or description only). Rules: E15-D12's (a measurement with its window and target, never a verdict; capabilities, never subsystem words; what still works in every reduced string) and E15-D15 R-5's spelled interval in every name and announcement. CP-31 is the announced form of CP-30: its first sentence, said once, assertive; the visible line stays CP-30. Figures are fixtures.

| Id    | String                                                                                                                 | Surface                          | Level     |
| ----- | ---------------------------------------------------------------------------------------------------------------------- | -------------------------------- | --------- |
| CP-01 | Grid · 2×2                                                                                                             | grid header, arrangement button  | visible   |
| CP-02 | One by two, two charts                                                                                                 | CMP-217 cell mode                | visible   |
| CP-03 | Two by two, four charts                                                                                                | CMP-217 cell mode                | visible   |
| CP-04 | Three by three, nine charts                                                                                            | CMP-217 cell mode                | visible   |
| CP-05 | One large and three small, four charts                                                                                 | CMP-217 cell mode                | visible   |
| CP-06 | Custom: 2 rows by 3 columns, six charts                                                                                | CMP-217 cell mode                | visible   |
| CP-07 | Each chart follows its own sync group.                                                                                 | grid header `Sync ▾`             | visible   |
| CP-08 | New charts join: Sync group A                                                                                          | grid header `Sync ▾`             | visible   |
| CP-09 | Add a chart to this grid cell                                                                                          | empty cell                       | visible   |
| CP-10 | Loading BTCUSDT 4 hours…                                                                                               | loading cell                     | visible   |
| CP-11 | ETHUSDT data unavailable                                                                                               | unavailable cell                 | visible   |
| CP-12 | ABCUSDT is no longer listed. This chart can't load it.                                                                 | delisted cell                    | visible   |
| CP-13 | 1 chart couldn't load: ABCUSDT                                                                                         | grid restore line                | polite    |
| CP-14 | History from 12 Mar                                                                                                    | short-history chip               | visible   |
| CP-15 | Chart trading: LOCKED (entry only). Maximise this chart to trade.                                                      | cell menu status line            | visible   |
| CP-16 | One-click trading disarmed: chart returned to the grid.                                                                | restore while armed              | polite    |
| CP-17 | Showing chart 3 of 4                                                                                                   | grid header, maximised           | visible   |
| CP-18 | Chart, BTCUSDT 4 hours, Live, maximised.                                                                               | maximise                         | polite    |
| CP-19 | Grid restored, 4 charts.                                                                                               | restore                          | polite    |
| CP-20 | Grid changed to 3 by 3, 9 charts.                                                                                      | arrangement change               | polite    |
| CP-21 | Chart, BTCUSDT 4 hours, Live, focused                                                                                  | cell focus                       | polite    |
| CP-22 | This grid has 4 charts.                                                                                                | `Ctrl+Alt+N` past the grid       | polite    |
| CP-23 | 3×3 to 2×2 removes 5 charts: SOLUSDT 1 hour, ETHUSDT 15 minutes and 3 more.                                            | shrink confirm                   | visible   |
| CP-24 | 3×3 needs about 21.4 ms per frame on this device (estimated); now 12.6 ms per frame (p95, measured). Target 16.6 ms.   | budget confirm                   | visible   |
| CP-25 | 9 charts take 24.1 ms per frame (p95, last minute, measured); target 16.6 ms.                                          | grid header, running             | visible   |
| CP-26 | Reduced                                                                                                                | grid header chip                 | visible   |
| CP-27 | Reduced: charts you aren't using update every 200 ms; heatmap depth one tier lower and footprint numbers hidden there. | chip name                        | none      |
| CP-28 | Every chart still shows its price, your orders and your positions.                                                     | reduced, what still works        | visible   |
| CP-29 | Disarming chart trading…                                                                                               | grid header, restore while armed | visible   |
| CP-30 | Chart trading is still armed on chart 3. Disarm, or maximise it to trade.                                              | grid header, disarm failed       | visible   |
| CP-31 | Chart trading is still armed on chart 3.                                                                               | disarm failed                    | assertive |
| CP-32 | Feed: Live; mark 64,011.5; last 64,011.0.                                                                              | cell menu status line            | visible   |

## 15. Analytics

Analytics, never audit; no sink exists yet (E15-D01 OQ-11). `multichart.grid_changed{arrangement}`, `multichart.cell_symbol_changed{cellIndex}`, `multichart.sync_group_changed`, `multichart.cell_maximised{cellIndex}` and `multichart.degraded_prompt_shown{cells, measuredFrameMs}` (added here; the frame time a bucket, never a raw device profile). `layout.maximised` stays the dock's. Registering the events in the catalogue is a hand-off row.

## 16. Buildability checklist

A builder can answer each from this page alone: the three cues (§2); the five arrangements and the shrink confirm (§3); the cell row's order and its two badges, the four steps and the widths where they fire, the never-dropped five, the minimum, the switcher and its details, and the measured cases (§4); the active-cell marker, how a cell becomes active and the panel frame side by side (§5); the keys, the names, the description's order, the cell menu's order and the announcements (§6); maximise, `Esc` and the exact restore (§7); LOCKED, the protective carve-out, the maximised arm state, the disarm and its failure (§8); the sync rule (§9); the five cell states (§10); the two moments of the budget prompt (§11); the five performance rules (§12); what is stored (§13); the copy (§14). A rebuild of one cell row from this page is the dry run the pack §21 asks the deputy for.
