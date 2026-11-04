# E21-D02 / 10 keyboard-table-reflow

File `E21-D02 boards`, page `E21-D02`; export `docs/design/E21/img/E21-D02-10-keyboard-table-reflow.png`; sheet `10-keyboard-table-reflow.json` (validated); theme dark.

Board 10 of 10 (§0 L109: §9 focus order and the row menu, §10 Table view, the 200 % reflow). Grid (25600, 3200); 3280 x 1667 px; "page E21-D02 · board 10 · r1".

## Frames

- `SCR-050∕streaming · focus order and row menu` (`SCR-050/streaming · focus order and row menu`)
- `SCR-050∕streaming · Table view` (`SCR-050/streaming · Table view`)
- `reflow · 200 %` (`reflow · 200 %`)
- `keys · §9.2` (`keys · §9.2`)

## Validator and size

- `10-keyboard-table-reflow.json: 0 errors, 27 warnings, 51 sections, 154817 bytes` (exit 0)
- 51 sections, 932 shapes, 154817 bytes

## Live checks (10)

- frame 'SCR-050∕streaming · focus order and row menu': the row menu is anchored at x 740, y 202 (below the 64,100 row); never centre it
- frame 'SCR-050∕streaming · focus order and row menu': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y or its flex parent's alignment — never apply a generic re-centre
- root 'E21-D02 / 10 keyboard-table-reflow' at (25600, 3200): read back the name exactly after the first section call; size 3280 x 1667
- after touchTexts + relayout: the root h 1667 is the live check's max(annotation end, footer end 1586) + 80 (the annotation column estimated 1083 px with 15 % slack); re-measure it if the annotations change
- frame 'SCR-050∕streaming · focus order and row menu': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕streaming · Table view': read back 1280 x 800 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'reflow · 200 %': read back 640 x 400 at (80, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'keys · §9.2': read back 1248 x 520 at (800, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D02-10-keyboard-table-reflow.png: record the board id and the PNG size

## Derivations (3)

- the focused row 64,100 reads its six cells from the world (§9.2's form; its examples are illustrative)
- Table view: 10 rows of the window (the table's own scroll, windowed); Change over the trail = the row's size now less its size 60 s ago
- 200 %: 640 × 400 CSS px; the ladder keeps Price, Bid (B), Ask (A), Your orders = 572 px, leaving 68 px < 25 % (160 px), so the pane hides behind the Heatmap toggle

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (37)

- spec L96: "BTCUSDT"
- spec L160: "mark 64,012.5"
- spec L147: "trail [60 s ▾]"
- spec L224: "T1 (2 s"
- spec L96: "Acct A"
- spec L96: "Acct B"
- spec L348: "pulled 18.0 (estimated)"
- spec L144: "BTCUSDT · Heatmap + Ladder"
- spec L84: "LOCKED"
- spec L152: "Following"
- spec L152: "Pause"
- spec L85: "DEMO"
- spec L151: "Ladder │ Table"
- W-1 (§12 L429, PROPOSED): "DOM ladder, BTCUSDT, DEMO"
- spec L224: "none"
- W-22 (§12 L450, verbatim): "Sell 0.5 limit" — the form of "Buy 0.5 limit", its illustrative figures derived from the world
- W-20 (§12 L448, PROPOSED; E09-D09 (A-5)): "Orders from here come later; cancel and close work as usual."
- W-25 (§12 L453, PROPOSED): "Long 0.30 · entry"
- W-23 (§12 L451, PROPOSED): "3 orders · buy 1.2 BTC"
- W-22 (§12 L450, verbatim): "Buy 0.5 limit"
- spec L258: "BUY MKT"
- spec L258: "SELL MKT"
- spec L259: "FLAT"
- spec L259: "CXL"
- spec L81: "limit"
- spec L86: "stop"
- spec L269: "TP"
- spec L263: "alert here"
- spec L263: "copy price"
- spec L396: "My levels only"
- spec L396: "load more rows"
- spec L13: "Price"
- spec L281: "Side"
- spec L160: "Resting size"
- spec L396: "Change over the trail"
- spec L396: "Estimated"
- spec L53: "(estimated)"

## Copy gaps (11)

- "depth": kit label, not E21-D02 copy — §2.1's `depth [200 ▾]` slot, its label word
- "announced: the focused row's reading (values update silently, R-7)": kit label, not E21-D02 copy — board-marker label
- "Heatmap · time →": kit label, not E21-D02 copy — §2.2's heading words as the pane's label
- "qty": kit label, not E21-D02 copy — `14`:1211's footer label
- "0.10 · 0.25 · 0.50 · 1.0": kit label, not E21-D02 copy — `14`:1211's qty presets (CMP-122); enabled, choosing one sends nothing
- "Detectors": kit label, not E21-D02 copy — the strip's label; CMP-134's words are E25's
- "Ladder table · the six columns of §2.3, `05`'s sort and filter": kit label, not E21-D02 copy — the table's caption
- "Bid": kit label, not E21-D02 copy — the Side column's word
- "Heatmap table (PROPOSED; `05` has no column set: G-4)": kit label, not E21-D02 copy — the table's caption
- "Heatmap": kit label, not E21-D02 copy — §9.4's toggle name
- "board marker — not product UI": kit label, not E21-D02 copy — board-marker caption

## Fallbacks (9)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock and the chevrons
- kit choice: the env badge's icon (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + icon, the colour never the only signal)
- kit choice: the `Ladder │ Table` radiogroup drawn as two 24 px segments, the checked one color.surface.selected with a color.border.selected outline
- kit choice: board markers (focus-order numbers, announcements, accessible names, redline callouts) are drawn in a 1 px color.border.strong outline — not product UI
- kit choice: the heatmap pane draws one row per ladder row (R-2) and one column per trail second (the cell chip's auto = 1 s), equal-stop runs drawn as one rect; compact and comfortable cells keep a 1 px gutter top and bottom, the cosy (`dense`) pane none (§3.1 'the pane's gutters tighter')
- kit choice: CMP-230's glyph (second, after the text) drawn as an 8 px square in color.buy.default or color.sell.default; the words carry the side
- kit choice: the pulled mark's hatch (pattern.hatch.estimated's look, D05E11 §7, cited not re-made) drawn as 2 × 2 steps of color.text.primary on a 6 px 45° track over the pulled cell
- kit choice: menus and the open listbox drawn as color.surface.overlay cards with a 1 px color.border.default outline (popovers over the rows)
- kit choice: focus-order numbers drawn as 20 px numbered markers in color.focus.ring (board markers)

## Sources (2)

- spec docs/design/E21/E21-D02.md md5 0431d0041dabe975c91a73421fa4e187 at the boards PR (§0 L109); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (54)

- type.ui.body-strong
- color.text.primary
- type.ui.caption
- color.text.secondary
- type.num.sm
- size.icon.sm
- space.inset.xs
- space.inset.sm
- color.surface.sunken
- color.border.default
- border.hairline
- radius.control
- space.button.paddingX
- size.icon
- color.env.demo
- border.thick
- type.ui.label
- color.surface.raised
- radius.badge
- color.surface.selected
- color.border.selected
- space.inset.md
- color.surface.canvas
- color.text.tertiary
- space.stack.xs
- color.border.strong
- color.heatmap.zero
- color.heatmap.ask.1
- color.heatmap.ask.2
- color.heatmap.ask.3
- color.grid.line
- color.heatmap.ask.4
- color.heatmap.ask.5
- color.sell.default
- color.heatmap.bid.2
- color.heatmap.bid.1
- color.heatmap.bid.3
- color.heatmap.bid.4
- color.heatmap.bid.5
- color.buy.default
- color.surface.app
- color.focus.ring
- border.focus
- type.ui.body
- color.surface.overlay
- radius.card
- color.text.on-action
- color.action.secondary.default
- space.stack.md
- space.stack.lg
- space.inset.xl
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
