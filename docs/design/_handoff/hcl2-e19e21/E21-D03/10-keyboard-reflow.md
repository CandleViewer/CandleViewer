# E21-D03 / 10 keyboard-reflow

File `E21-D03 boards`, page `E21-D03`; export `docs/design/E21/img/E21-D03-10-keyboard-reflow.png`; sheet `10-keyboard-reflow.json` (validated); theme dark.

Board 10 of 10 (§0 L119: SCR-051/unsaved-esc; §13 focus order, the 200 % reflow). Grid (25600, 3200); 2640 x 1528 px; "page E21-D03 · board 10 · r1".

## Frames

- `SCR-051∕unsaved-esc` (`SCR-051/unsaved-esc`)
- `reflow · 200 %` (`reflow · 200 %`)

## Validator and size

- `10-keyboard-reflow.json: 0 errors, 2 warnings, 30 sections, 69582 bytes` (exit 0)
- 30 sections, 382 shapes, 69582 bytes

## Live checks (6)

- board 10: every focus-order marker sits at its control's top-left corner; nudge in 4 px steps if not
- root 'E21-D03 / 10 keyboard-reflow' at (25600, 3200): read back the name exactly after the first section call; size 2640 x 1528
- after touchTexts + relayout: the annotation column (estimated 1366 px with 15 % slack) ends inside the root (h 1528); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-051∕unsaved-esc': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'reflow · 200 %': read back 640 x 400 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D03-10-keyboard-reflow.png: record the board id and the PNG size

## Derivations (5)

- SCR-050 behind: 31 rows at compact around mark 64,560.2 (best bid 64,560.2, best ask 64,560.3); cum. depth from the touch; prints = the drop between the last two columns within 6 levels; own orders Buy 0.250 at 64,559.8, Sell 0.100 at 64,560.9
- W-7 at 50: p95 3.2 ms, inbound 81/s from the kit model (seed 503, 2.4 + 0.011 ms × levels, p95 of 600 frames; 10 s of 20 Hz updates at p 0.04 a level) — illustrative, PROPOSED, not a budget
- W-7 at 200: p95 5.6 ms, inbound 326/s from the kit model (seed 503, 2.4 + 0.011 ms × levels, p95 of 600 frames; 10 s of 20 Hz updates at p 0.04 a level) — illustrative, PROPOSED, not a budget
- focus-order markers placed by the kit's size estimates (live check: each marker at its control's top-left)
- 200 % of the 1280 × 800 window = a 640 × 400 CSS px viewport; drawn in CSS px

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (38)

- spec L106: "BTCUSDT"
- spec L13: "illustrative, PROPOSED, not a budget"
- W-29 (§15 L474, PROPOSED): "Unsaved changes. Press Esc again to discard them."
- W-37 (§15 L482, PROPOSED): "Defaults restored. Not saved yet."
- W-37 (§15 L482, PROPOSED): "This tab's defaults restored. Not saved yet."
- spec L30: "DEMO"
- spec L99: "Reset to defaults"
- spec L151: "Reset this tab"
- spec L140: "Cancel"
- spec L5: "Save"
- spec L211: "levels per side"
- spec L180: "Trail length (s)"
- spec L163: "Decay"
- spec L163: "Smooth"
- W-14 (§15 L459, verbatim): "Auto — 1 s on this pane"
- spec L214: "100 ms"
- spec L214: "250 ms"
- spec L214: "500 ms"
- spec L3: "1 s"
- spec L144: "5 s"
- spec L159: "Depth tier"
- W-15 (§15 L460, PROPOSED): "Keep this tier under load"
- spec L213: "Row aggregation (ticks per row)"
- spec L23: "Columns"
- W-6 (§15 L451, PROPOSED): "A deeper tier uses more bandwidth and CPU on this device."
- W-7 (§15 L452, PROPOSED): "50 levels: frame time p95 3.2 ms · inbound 81/s, measured here"
- W-7 (§15 L452, PROPOSED): "200 levels: frame time p95 5.6 ms · inbound 326/s, measured here"
- W-8 (§15 L453, PROPOSED): "500: not yet measured on this device"
- spec L184: "Ask"
- spec L184: "Bid"
- W-1 (§15 L446, verbatim): "Heatmap + Ladder settings"
- W-2 (§15 L447, PROPOSED): "Heatmap + Ladder settings, BTCUSDT, DEMO"
- spec L96: "Depth & scale"
- spec L98: "Colour"
- spec L96: "Ladder"
- spec L97: "Trading"
- spec L121: "Detectors"
- spec L218: "Space or Enter re-shows W-3"

## Copy gaps (12)

- "announced: polite, once": kit label, not E21-D03 copy — board-marker label
- "announced: polite, once, on Reset to defaults · on Reset this tab (W-37)": kit label, not E21-D03 copy — board-marker label
- "depth": kit label, not E21-D03 copy — E21-D02's header
- "BTCUSDT · Heatmap + Ladder": kit label, not E21-D03 copy — E21-D02's panel title
- "Ladder │ Table": kit label, not E21-D03 copy — E21-D02's view switch
- "Heatmap (time →)": kit label, not E21-D03 copy — E21-D02's pane
- "Price": kit label, not E21-D03 copy — E21-D02's ladder column header
- "Bid (B)": kit label, not E21-D03 copy — E21-D02's ladder column header
- "Ask (A)": kit label, not E21-D03 copy — E21-D02's ladder column header
- "Prints": kit label, not E21-D03 copy — E21-D02's ladder column header
- "Cum. depth": kit label, not E21-D03 copy — E21-D02's ladder column header
- "Your orders": kit label, not E21-D03 copy — E21-D02's ladder column header

## Fallbacks (7)

- kit choice: board markers (focus-order numbers, announcements, hidden names, illustrative labels, redline callouts) are drawn in a 1 px color.border.strong outline with a 'board marker' caption — not product UI
- kit choice: the SCR-050 panel behind the dialog (E21-D02 #440's anatomy) is drawn as context at compact: header, the heatmap pane as run-length cells, the ladder's six columns; its labels are E21-D02's, listed as copy gaps here
- kit choice: the env pill's glyph (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + glyph, the colour never the only signal)
- opacity.scrim is a Tier-1 primitive (validator WARN): the SCR-050 panel behind the modal dialog is dimmed by a color.surface.app rect at opacity.scrim (CMP-043's backdrop)
- kit choice: CMP-006 radios drawn as 16 px circles (1 px color.text.tertiary rest stroke, E05-D04 F-03), the checked one with an 8 px color.action.primary.default dot; CMP-005 checkboxes as 16 px squares, checked filled color.action.primary.default with the local 'check' glyph in color.text.on-action
- kit choice: the CMP-228 tile's sample frame is 17 time columns × 10 price bands (5 a side, each band the sum of tier ÷ 5 levels), equal-bucket runs drawn as one rect; the stops bucket each band's size
- kit choice: focus-order numbers drawn as 20 px numbered markers in color.focus.ring (board markers)

## Sources (2)

- spec docs/design/E21/E21-D03.md md5 4f4755b45b309e4f1b11a728ce58dcda at c7b0d2087 (§0 L119); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (51)

- type.ui.caption
- color.text.tertiary
- color.text.primary
- space.stack.xs
- space.inset.sm
- color.surface.canvas
- color.border.strong
- border.hairline
- radius.control
- space.inset.lg
- color.text.secondary
- type.num.base
- size.icon
- space.inset.xs
- color.surface.sunken
- type.ui.body-strong
- color.env.demo
- border.thick
- type.ui.label
- color.surface.raised
- radius.badge
- space.inset.md
- color.heatmap.ask.2
- color.heatmap.ask.1
- type.num.sm
- color.heatmap.ask.3
- color.heatmap.ask.4
- color.heatmap.ask.5
- color.heatmap.bid.2
- color.heatmap.bid.3
- color.heatmap.bid.4
- color.heatmap.bid.1
- opacity.scrim
- color.surface.app
- space.button.paddingX
- color.action.secondary.default
- color.text.on-action
- color.action.primary.default
- space.dialog.padding
- type.ui.body
- color.focus.ring
- border.focus
- space.stack.sm
- color.border.default
- space.stack.md
- color.heatmap.zero
- color.heatmap.bid.5
- type.ui.heading-sm
- color.border.selected
- color.surface.overlay
- radius.dialog
