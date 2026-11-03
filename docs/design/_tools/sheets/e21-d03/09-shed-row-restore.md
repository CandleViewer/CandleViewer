# E21-D03 / 09 shed-row-restore

File `E21-D03 boards`, page `E21-D03`; export `docs/design/E21/img/E21-D03-09-shed-row-restore.png`; sheet `09-shed-row-restore.json` (validated); theme dark.

Board 09 of 10 (§0 L118: SCR-153/depth-shed, SCR-153/depth-pinned, SCR-153/depth-restored; the greyscale export). Grid (19200, 3200); 3280 x 1934 px; "page E21-D03 · board 09 · r1".

Light twin: export this board again under the light theme as `docs/design/E21/img/E21-D03-09-shed-row-restore-light.png` (token-bound; §0 dark + light).

## Frames

- `SCR-153∕depth-shed` (`SCR-153/depth-shed`)
- `SCR-153∕depth-pinned` (`SCR-153/depth-pinned`)
- `SCR-153∕depth-restored` (`SCR-153/depth-restored`)

## Validator and size

- `09-shed-row-restore.json: 0 errors, 1 warnings, 26 sections, 107193 bytes` (exit 0)
- 26 sections, 668 shapes, 107193 bytes

## Live checks (7)

- light twin: after the dark export, switch to the light theme (wait as the sheets README says) and export the same board as docs/design/E21/img/E21-D03-09-shed-row-restore-light.png
- root 'E21-D03 / 09 shed-row-restore' at (19200, 3200): read back the name exactly after the first section call; size 3280 x 1934
- after touchTexts + relayout: the root h 1934 is the live check's max(annotation end, footer end) + 80 (estimated 1934: the annotation column 1136 px); re-measure it if the annotations change
- frame 'SCR-153∕depth-shed': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-153∕depth-pinned': read back 1280 x 800 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-153∕depth-restored': read back 1280 x 800 at (80, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D03-09-shed-row-restore.png: record the board id and the PNG size

## Derivations (3)

- SCR-050 behind: 26 rows at compact around mark 64,560.2 (best bid 64,560.2, best ask 64,560.3); cum. depth from the touch; prints = the drop between the last two columns within 6 levels; own orders Buy 0.250 at 64,559.8, Sell 0.100 at 64,560.9
- SCR-050 behind: 28 rows at compact around mark 64,560.2 (best bid 64,560.2, best ask 64,560.3); cum. depth from the touch; prints = the drop between the last two columns within 6 levels; own orders Buy 0.250 at 64,559.8, Sell 0.100 at 64,560.9
- SCR-050 behind: 30 rows at compact around mark 64,560.2 (best bid 64,560.2, best ask 64,560.3); cum. depth from the touch; prints = the drop between the last two columns within 6 levels; own orders Buy 0.250 at 64,559.8, Sell 0.100 at 64,560.9

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (10)

- spec L106: "BTCUSDT"
- spec L13: "illustrative, PROPOSED, not a budget"
- W-25 (§15 L470, verbatim): "Pin depth 200"
- W-22 (§15 L467, PROPOSED): "Ladder depth lowered 200 → 50: drawing fell behind for 5 s. Levels beyond 50 are hidden."
- W-23 (§15 L468, PROPOSED): "Orders, positions, fills, alerts, stops and the environment badge keep full speed."
- W-24 (§15 L469, PROPOSED): "Depth returns to 200 when drawing keeps up."
- W-21 (§15 L466, verbatim; final here): "Depth 200 → 50 — levels 51–200 hidden · Pin 200"
- spec L30: "DEMO"
- W-26 (§15 L471, PROPOSED): "Depth 200 pinned. Drawing is still behind; orders and positions keep full speed."
- W-27 (§15 L472, PROPOSED): "Ladder depth back to 200."

## Copy gaps (12)

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
- "announced: polite, once (the banner's role="status")": kit label, not E21-D03 copy — board-marker label
- "pinned": kit label, not E21-D03 copy — E21-D02's pin display

## Fallbacks (3)

- kit choice: the SCR-050 panel behind the dialog (E21-D02 #440's anatomy) is drawn as context at compact: header, the heatmap pane as run-length cells, the ladder's six columns; its labels are E21-D02's, listed as copy gaps here
- kit choice: the env pill's glyph (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + glyph, the colour never the only signal)
- kit choice: board markers (focus-order numbers, announcements, hidden names, illustrative labels, redline callouts) are drawn in a 1 px color.border.strong outline with a 'board marker' caption — not product UI

## Sources (2)

- spec docs/design/E21/E21-D03.md md5 b22ff82ca51787f3bbecc5f8d34fd6bf, as built (cites read at c7b0d2087; §0 L118); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (44)

- type.ui.body-strong
- color.text.primary
- space.button.paddingX
- radius.control
- space.inset.sm
- color.action.secondary.default
- type.ui.body
- type.ui.caption
- color.text.secondary
- space.stack.xs
- color.status.info.strong
- size.icon
- space.inset.md
- space.inset.lg
- color.status.info.subtle
- type.num.base
- space.inset.xs
- color.surface.sunken
- color.text.tertiary
- border.hairline
- color.env.demo
- border.thick
- type.ui.label
- color.surface.raised
- radius.badge
- color.surface.canvas
- color.status.warning.strong
- color.status.warning.subtle
- color.heatmap.ask.2
- color.heatmap.ask.3
- type.num.sm
- color.heatmap.ask.1
- color.heatmap.ask.4
- color.heatmap.ask.5
- color.heatmap.bid.2
- color.heatmap.bid.3
- color.heatmap.bid.4
- color.heatmap.bid.1
- color.border.strong
- color.surface.app
- color.focus.ring
- border.focus
- type.ui.heading-sm
- space.stack.sm
