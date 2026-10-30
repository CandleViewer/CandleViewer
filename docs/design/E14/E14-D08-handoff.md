# E14-D08 — Hand-off (`16` §11.4): the two checklists (CMP-191, CMP-223)

Components: CMP-191 DrawingToolOverlay and CMP-223 DrawingToolbar. The pack is [E14-D08.md](E14-D08.md) (every "A-n" below is its §C row, applied to `15` by PR 2; every "L-n" its §2 ledger row). This ticket **changes two component contracts** and attaches a checklist for each (`16` §11.4, §13.3 item 8); CMP-031's checklist is D04H's, and the fib / VWAP / measure and position-tool blocks of CMP-191 are D05H's and D06H's — cited, not re-written. The tables cite `15` by entry and never restate a props table; the keyboard tables add no global binding (`05` §3.2) and leave `Esc` and `Ctrl+K` untouched (`05` §3.3).

Rule: every line is `[x]` with its evidence, or `[ ]` with its reason (a PR still to land, or `N/A — <reason>`). No blank line at Done (`16` §11.4, §13.3).

## The A-row ledger by component

The pack's §2 holds the ledger: 42<!--=COUNT:ledger--> rows, 21<!--=COUNT:ledger.applied--> applied, 14<!--=COUNT:ledger.amended--> applied-as-amended, 7<!--=COUNT:ledger.routed--> routed, 0<!--=COUNT:ledger.held--> held. Per target, the rows its A-rows carry (the tool derives this table from §2 and §C):

| Component | Ledger rows                                                   | A-rows      |
| --------- | ------------------------------------------------------------- | ----------- |
| §0.1      | L-42                                                          | A-1         |
| CMP-191   | L-1, L-4, L-6, L-28, L-29, L-31, L-33, L-34, L-35, L-36, L-39 | A-2 … A-12  |
| CMP-223   | L-2, L-7, L-13, L-14, L-15                                    | A-13 … A-20 |
| CMP-192   | L-5                                                           | A-21        |
| CMP-019   | L-8, L-40                                                     | A-22        |
| CMP-031   | L-16                                                          | A-23 … A-25 |
| CMP-005   | L-17                                                          | A-26, A-27  |
| CMP-008   | L-18                                                          | A-28, A-29  |
| CMP-010   | L-19                                                          | A-30, A-31  |
| CMP-009   | L-20                                                          | A-32 … A-34 |
| CMP-017   | L-21                                                          | A-35        |
| CMP-227   | L-30                                                          | A-36        |
| SCR-037   | —                                                             | A-37        |

## Handoff checklist — CMP-191 DrawingToolOverlay (E14-D08, #352)

- [ ] **Final Penpot link** — PR 3: file CandleViewer DS, page `E14-D08 Drawing primitives`, boards 01, 03, 04, 05, 06, 07 and 09 (the reference frames of `16` §10 item 4, one per state), referenced by page name + page id only; PNGs under `docs/design/E14/img/E14-D08-NN-*.png`
- [x] **Variants × States matrix** — table 1; the stories of A-10 48<!--=COUNT:stories.191-->); the fib / VWAP / measure frames are D05H's Table 1 and the position frames D06H's Table 1, cited
- [x] **Keyboard table** — table 2: E14-D02 §5.8 Table 2 cited row by row (A-5), with D05H's anchor-count rows and D06H's position rows
- [x] **Accessible name / role table** — table 3: E14-D02 §5.8 Table 3 cited (A-5)
- [x] **Live data** — table 5: the shared polite `status` region, coalesced; nothing per tick
- [x] **Motion pair** — N/A — none animated by design (A-12's Motion line; E14-D09 owns the pairs)
- [x] **Density notes** — the density table: handles, targets and the magnet radius in CSS px at every density; the chip 20 / 24 / 20 and 32 / 36 / 32 (compact / comfortable / dense)
- [x] **Essential-exceptions log** — none here; the brush's keyboard-path exception is E14-D02 §17.5's, cited by D02's own log
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (A-6); the Penpot sets equal `packages/ui/tokens` at a0132de011<!--=SHA:TOK-->; every PROPOSED name is a row of the pack's §4.1 or a cited `E13D03` / `E11D05` alias
- [x] **Data contract confirmed** — `22` `Drawing` / `DrawingTool` (25 values, required point counts) / `DrawingStyle` (`colour` hex today; the token-id form is G-1), `21` §3.8.3's `drawings.style jsonb`; `createDrawing` / `updateDrawing` under `workspaces:write`; the gaps G-1, G-2, G-6 recorded with the shared sentence
- [x] **Contrast and CVD** — computed by the tool: the pack's §8 (P-1 … P-22 in three themes, 18<!--=COUNT:pairs.gated--> gated, 0<!--=COUNT:pairs.failing--> failing; V-1 … V-6); the `PAIRS` rows PROPOSED are §4.3's, exported de-duplicated with the parents' by the tool's `--pairs`; the renders beside boards 01 / 03 / 04 / 06 land with PR 3
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — the orchestrator's design approval on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant                     | State                                                                                                | Penpot frame (PR 3)              | Story name                                                                                                                                                                                                                                                       |
| --------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| lines · shapes (base tools) | default · hover · `placing(n)` · selected · multi-select · locked · hidden · unsaved · conflict · T2 | `E14-D08/state-<state>` (06, 07) | Trendline, Ray, HLine, Rectangle, Fibonacci, Handles, Selected, MultiSelected, Locked, Hidden, Unsaved, Conflict, ViewerReadOnly, ViewAsReadOnly, TwoHundredDrawings                                                                                             |
| the other R1 tools          | default (one of each, D02 §2.2's registry)                                                           | 07                               | ExtendedLine, VerticalLine, Ellipse, Triangle, ParallelChannel, Text, Callout, Arrow, Polyline                                                                                                                                                                   |
| keyboard draw               | one · two · three anchors · the unbounded class (the polyline)                                       | — (D02's boards)                 | KeyboardDrawDemo, KeyboardDrawOneAnchor, KeyboardDrawThreeAnchors, KeyboardDrawUnbounded                                                                                                                                                                         |
| fib · VWAP · measure (D05H) | D05H Table 1's frames, cited                                                                         | — (D05's boards, pending)        | FibRetracement, FibRetracementInverted, FibCompressed5Cases, FibCustom0886, FibExtension, FibTimeZones, AnchoredVwap, AnchoredVwapBands, AnchoredVwapEstimated, AnchoredVwapBesideIndicator, MeasureTransient, MeasurePinned, MeasureAcrossGap, DensityComposite |
| position tool (D06H)        | D06H Table 1's frames, cited                                                                         | — (D06's boards)                 | PositionTool                                                                                                                                                                                                                                                     |
| palette and themes          | nine swatches on both canvases · high contrast · forced-colors · reduced motion · greyscale          | 03, 04, 09 (06 for greyscale)    | Palette, HighContrast, ForcedColors, ReducedMotion, Greyscale                                                                                                                                                                                                    |

### Table 2 — Keyboard

| Key                                   | Action                                                                                                                                                                                  | Focus after                            | Global conflict?                                                  | Notes                                |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- | ----------------------------------------------------------------- | ------------------------------------ |
| `Tab` / `Shift+Tab`                   | enter / leave the handles stop (one roving set after the plot stop)                                                                                                                     | the drawing's first surrogate          | none                                                              | E14-D02 §5.8 Table 2, cited          |
| `↑` / `↓`, `←` / `→`, `Shift` ×10     | move the focused handle one tick / one bar (the whole drawing on the object surrogate)                                                                                                  | unchanged; the readout coalesced       | none inside the stop; never on the plot stop                      | E14-D02 §5.8                         |
| `PageUp` / `PageDown`, `Home` / `End` | previous / next surrogate, first / last (time then price)                                                                                                                               | that surrogate                         | none inside the stop                                              | E14-D02 §9.4; CMP-192 aligned (A-21) |
| `Enter`                               | open the properties popover; while placing: commit the pending anchor (one per anchor count; the polyline closes on `Shift+Enter`, or `Enter` on the previous point — E14-D02 §4.3 T27) | the popover's first field / unchanged  | none                                                              | E14-D02 §5.8, §4.4; D05H (1 / 2 / 3) |
| `Space`                               | toggle the drawing's selection                                                                                                                                                          | unchanged                              | none inside the stop                                              | E14-D02 §5.8                         |
| `Del` / `Backspace`                   | delete (one undo)                                                                                                                                                                       | the next surrogate, else the plot stop | `chart.delete_drawing` registered; `Backspace` PROPOSED (D02 G10) | E14-D02 §5.8                         |
| `Ctrl+↑` / `Ctrl+↓`                   | cycle the pending anchor's snap through O / H / L / C                                                                                                                                   | unchanged                              | none (unregistered, not in `05` §3.2)                             | E14-D02 §6, Q7 PROPOSED              |
| `Esc`                                 | clear the selection and return to the plot stop (the ladder's last level)                                                                                                               | the plot stop                          | reserved                                                          | E14-D02 §5.8                         |
| `Shift+F10` / Menu                    | the drawing's context menu (Clone · Lock · Hide · Properties · Delete; Switch side on the position tool)                                                                                | the menu                               | OS gesture                                                        | E14-D02 §5.8; E14-D06 D16            |
| the edit keys on a T2 session         | nothing changes; the reason announced once                                                                                                                                              | unchanged                              | none                                                              | E14-D02 §5.8's T2 row                |

### Table 3 — Accessible name / role

| Element               | Role                     | Name source                                                                                                                                                                           | States / properties                                                                                    |
| --------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| the handles set       | `group`                  | "Drawings on BTCUSDT 1m, 12 items" (E14-D02 Table 3)                                                                                                                                  | roving `tabindex`; `aria-setsize` / `aria-posinset`; `aria-describedby` → the Page Up / Page Down hint |
| an object surrogate   | `button`                 | "Trendline 13:40 → 14:05, item 3 of 12" (+ "locked", "hidden", "this pane only", "not saved"; "Default colour (unknown stored colour)" on the fallback, PROPOSED — E14-D10 finalises) | `aria-pressed` for selected; T2 → `aria-describedby` the pane's reason node                            |
| an anchor surrogate   | `button`                 | "Trendline, anchor 1 of 2, 13:40 64,012.5"                                                                                                                                            | `aria-describedby` → the snap text while a snap candidate shows                                        |
| the from → to readout | `status` (shared region) | "Moved 64,000 to 64,120. Undo available."                                                                                                                                             | polite, coalesced                                                                                      |
| the position read-out | `region` (`<dl>`)        | D06H Table 3, cited (CMP-036 rows; Send to ticket last)                                                                                                                               | D06H, cited                                                                                            |

### Table 4 — Motion pair

| Property | Motion-safe | Motion-reduce | Notes                                                            |
| -------- | ----------- | ------------- | ---------------------------------------------------------------- |
| none     | —           | —             | none animated by design; E14-D09 (#353) appends the pairs (A-12) |

### Table 5 — Live data

| Field                 | Politeness             | Cadence                                                 | Coalesced to                          |
| --------------------- | ---------------------- | ------------------------------------------------------- | ------------------------------------- |
| the from → to readout | polite (shared region) | E06-D03 D5's cadence, only while a surrogate has focus  | the latest value                      |
| the snap text         | via `aria-describedby` | per candidate, before commit only                       | the current candidate                 |
| the measure chip      | none                   | local arithmetic over loaded bars, no server round-trip | the current drag                      |
| the position plan     | none on the canvas     | the engine cadence; the drawings layer alone dirties    | the plan object (D06H Table 5, cited) |

### Density

| Mode        | Handle target | Glyph | Chip (one / two lines) | Label minimum | Smallest target        |
| ----------- | ------------- | ----- | ---------------------- | ------------- | ---------------------- |
| compact     | 24 × 24 px    | 8 px  | 20 / 32 px             | 11 px CSS     | 24 × 24 px (the floor) |
| comfortable | 24 × 24 px    | 8 px  | 24 / 36 px             | 11 px CSS     | 24 × 24 px             |
| dense       | 24 × 24 px    | 8 px  | 20 / 32 px             | 11 px CSS     | 24 × 24 px (the floor) |

### Essential exceptions

none — click-click placement, the anchor fields and the keyboard flow are the 2.5.7 alternatives (E14-D02 §9); the brush's keyboard-path exception is E14-D02 §17.5's, logged there.

## Handoff checklist — CMP-223 DrawingToolbar (E14-D08, #352)

- [ ] **Final Penpot link** — PR 3: file CandleViewer DS, page `E14-D08 Drawing primitives`, component `CMP-223 · DrawingToolbar` (board 08, the one true Penpot component), referenced by page name + page id only; PNG under `docs/design/E14/img/E14-D08-08-*.png`; the rail's own frames are D03H's (page `E14-D03 Drawing tool rail and palette`)
- [x] **Variants × States matrix** — table 1; the stories of A-17 18<!--=COUNT:stories.223-->); D03H's Table 1 cited for the frames
- [x] **Keyboard table** — table 2: E14-D02 §3.4 Table 2 as D03H cites it, plus the chord row of A-15
- [x] **Accessible name / role table** — table 3: E14-D02 §3.4 Table 3 as D03H cites it
- [x] **Live data** — table 5: the hide-all count is the one live value (D03H)
- [x] **Motion pair** — N/A — none animated on the rail by design (A-20's Motion line)
- [x] **Density notes** — the density table: 24 / 32 px buttons, the 16 px glyph, `space.1` padding
- [x] **Essential-exceptions log** — none (24 × 24 is exactly `size.target.min`)
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (A-16 = E14-D03 §9.3); the Penpot sets equal `packages/ui/tokens` at a0132de011<!--=SHA:TOK-->
- [x] **Data contract confirmed** — the rail arms tools and writes nothing itself; lock-all → `updateDrawing` / `batchUpsertDrawings` (`DrawingInput.locked`), delete-all → the batch with one undo, hide-all a per-pane view state; magnet mode, keep tool active and "Show tool rail" → `PATCH /settings` under PROPOSED keys (D02 G6; G-3)
- [x] **Contrast and CVD** — D03H's numbers (spec D03 §9: 30 pairs × 3 themes, 24 gated, FAIL 0; 9 CVD rows) stand unchanged; this pack adds no rail pair
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on board 08
- [ ] **Sign-off** — the orchestrator's design approval on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant     | State                                                                                                                                                                                                          | Penpot variant (PR 3)                                     | Story name                                                                                                                                                                                                       |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| compact     | default · hover · focus-visible · armed · keep-active · magnet off / weak / strong · all-locked · all-hidden · overflowing · collapsed · Viewer · view-as · zoom 200 % · high contrast · forced-colors · light | CMP-223 · DrawingToolbar / Density=Compact, State=<state> | Default, ToolActive, KeepActive, MagnetOff, MagnetWeak, MagnetStrong, AllLocked, AllHidden, Overflowing, CollapsedDraw, ViewerReadOnly, ViewAsReadOnly, FocusVisible, Zoom200, HighContrast, ForcedColors, Light |
| comfortable | default                                                                                                                                                                                                        | CMP-223 · DrawingToolbar / Density=Comfortable            | Comfortable                                                                                                                                                                                                      |

### Table 2 — Keyboard

| Key                                               | Action                                                                                                                             | Focus after               | Global conflict?                                      | Notes                           |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------- | ----------------------------------------------------- | ------------------------------- |
| `Tab` / `Shift+Tab`                               | the rail is one roving stop after the status chips                                                                                 | the active or first tool  | none                                                  | E14-D02 §3.4 Table 2 (D03H)     |
| `↑` / `↓`, `Home` / `End`                         | move between the rail's items                                                                                                      | that item                 | none inside the stop                                  | E14-D02 §3.4                    |
| `Enter` / `Space`                                 | arm the tool and move focus to the plot stop; again on the armed tool disarms                                                      | the plot stop / unchanged | none                                                  | E14-D02 §3.4; E14-D03 §11 tests |
| `Alt+L` `Alt+H` `Alt+O` `Alt+R` `Alt+D`, `Ctrl+M` | arm trendline / horizontal line / fib retracement / rectangle / measure; magnet toggle — interim scheme (a), registered by E14-S10 | the plot stop             | registered by E14-S10; `Alt+D` / `Cmd+M` are D02 G5's | A-15; E14-D02 §3.4, C14         |
| `Esc`                                             | the ladder; with nothing armed on the rail it is not consumed                                                                      | per the ladder            | reserved                                              | E14-D02 §3.4                    |
| `Shift+F10` / Menu on a tool button               | the tool button's context menu                                                                                                     | the menu                  | OS gesture                                            | E14-D03 §5.5                    |
| a T2 control                                      | nothing changes; one polite announcement                                                                                           | unchanged                 | none                                                  | E09-D09 §2.2; E14-D03 A2        |

### Table 3 — Accessible name / role

| Element             | Role                            | Name source                                                             | States / properties                                                                      |
| ------------------- | ------------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| the rail            | `toolbar` (vertical)            | "Drawing tools" (E14-D02 §3.4 Table 3, D03H)                            | roving `tabindex`                                                                        |
| a tool button       | `button`                        | the tool name; the chord in the tooltip via CMP-022, `aria-describedby` | `aria-pressed` when armed                                                                |
| the magnet button   | `button` `aria-haspopup="menu"` | "Magnet: weak" (the mode in the name)                                   | the menu's `menuitemradio` items                                                         |
| lock-all / hide-all | `button` toggles                | "Lock all drawings" / "200 drawings hidden" (D03H)                      | `aria-pressed`; `aria-live="off"` on the count                                           |
| "Show tool rail"    | `menuitemcheckbox` in `[Draw]`  | "Show tool rail" (A-14, RULED yes)                                      | `aria-checked`; T2 per E14-D03 §8.1 (view-as first, then `settings:write`; rendering 2a) |
| a gated control     | as its control                  | its name, led by the CMP-019 `lock` "Not available"                     | `aria-disabled` + `aria-describedby` → the reason; never `disabled`                      |

### Table 4 — Motion pair

| Property | Motion-safe | Motion-reduce | Notes                                                            |
| -------- | ----------- | ------------- | ---------------------------------------------------------------- |
| none     | —           | —             | nothing on the rail animates by design (E14-D03 §4 row 19; A-20) |

### Table 5 — Live data

| Field              | Politeness                      | Cadence                   | Coalesced to                  |
| ------------------ | ------------------------------- | ------------------------- | ----------------------------- |
| the hide-all count | `aria-live="off"` on the button | the toggle announces once | the current count (D03H)      |
| the armed chip     | `status`, `aria-live="off"`     | on arm / disarm           | the armed tool (E14-D02 §3.2) |

### Density

| Mode        | Button     | Glyph | Padding   | Smallest target        |
| ----------- | ---------- | ----- | --------- | ---------------------- |
| compact     | 24 × 24 px | 16 px | `space.1` | 24 × 24 px (the floor) |
| comfortable | 32 × 32 px | 16 px | `space.1` | 32 × 32 px             |

### Essential exceptions

none — 24 × 24 is exactly `size.target.min`; CMP-002's "44 px comfortable" line is D03's C-row, not an exception.
