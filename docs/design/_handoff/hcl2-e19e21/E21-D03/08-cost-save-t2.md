# E21-D03 / 08 cost-save-t2

File `E21-D03 boards`, page `E21-D03`; export `docs/design/E21/img/E21-D03-08-cost-save-t2.png`; sheet `08-cost-save-t2.json` (validated); theme dark.

Board 08 of 10 (§0 L117: SCR-051/cost-unmeasured, SCR-051/save-gated). Grid (12800, 3200); 3280 x 1352 px; "page E21-D03 · board 08 · r1".

## Frames

- `SCR-051∕cost-unmeasured` (`SCR-051/cost-unmeasured`)
- `SCR-051∕save-gated` (`SCR-051/save-gated`)
- `specimen · the W-33 leg` (`specimen · the W-33 leg`)

## Validator and size

- `08-cost-save-t2.json: 0 errors, 7 warnings, 27 sections, 89621 bytes` (exit 0)
- 27 sections, 525 shapes, 89621 bytes

## Live checks (6)

- root 'E21-D03 / 08 cost-save-t2' at (12800, 3200): read back the name exactly after the first section call; size 3280 x 1352
- after touchTexts + relayout: the annotation column (estimated 870 px with 15 % slack) ends inside the root (h 1352); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-051∕cost-unmeasured': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-051∕save-gated': read back 1280 x 800 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'specimen · the W-33 leg': read back 1008 x 200 at (80, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D03-08-cost-save-t2.png: record the board id and the PNG size

## Derivations (3)

- SCR-050 behind: 31 rows at compact around mark 64,560.2 (best bid 64,560.2, best ask 64,560.3); cum. depth from the touch; prints = the drop between the last two columns within 6 levels; own orders Buy 0.250 at 64,559.8, Sell 0.100 at 64,560.9
- W-7 at 50: p95 3.2 ms, inbound 81/s from the kit model (seed 503, 2.4 + 0.011 ms × levels, p95 of 600 frames; 10 s of 20 Hz updates at p 0.04 a level) — illustrative, PROPOSED, not a budget
- W-7 at 200: p95 5.6 ms, inbound 326/s from the kit model (seed 503, 2.4 + 0.011 ms × levels, p95 of 600 frames; 10 s of 20 Hz updates at p 0.04 a level) — illustrative, PROPOSED, not a budget

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (38)

- spec L106: "BTCUSDT"
- spec L13: "illustrative, PROPOSED, not a budget"
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
- W-8 (§15 L453, PROPOSED): "50: not yet measured on this device"
- W-8 (§15 L453, PROPOSED): "200: not yet measured on this device"
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
- W-32 (§15 L477, verbatim): "Read-only while viewing as Manager 01."
- W-7 (§15 L452, PROPOSED): "50 levels: frame time p95 3.2 ms · inbound 81/s, measured here"
- W-7 (§15 L452, PROPOSED): "200 levels: frame time p95 5.6 ms · inbound 326/s, measured here"
- W-33 (§15 L478, the key's string with the D09E09:114 verb): "Your role can't save workspaces."

## Copy gaps (13)

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
- "announced: polite, on each Enter / Space on Save (G-T2.3, R-5)": kit label, not E21-D03 copy — board-marker label
- "Without workspaces:write (the second leg): the footer": kit label, not E21-D03 copy — board-marker caption
- "board marker — not product UI": kit label, not E21-D03 copy — board-marker caption

## Fallbacks (7)

- kit choice: the SCR-050 panel behind the dialog (E21-D02 #440's anatomy) is drawn as context at compact: header, the heatmap pane as run-length cells, the ladder's six columns; its labels are E21-D02's, listed as copy gaps here
- kit choice: the env pill's glyph (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + glyph, the colour never the only signal)
- opacity.scrim is a Tier-1 primitive (validator WARN): the SCR-050 panel behind the modal dialog is dimmed by a color.surface.app rect at opacity.scrim (CMP-043's backdrop)
- kit choice: CMP-006 radios drawn as 16 px circles (1 px color.text.tertiary rest stroke, E05-D04 F-03), the checked one with an 8 px color.action.primary.default dot; CMP-005 checkboxes as 16 px squares, checked filled color.action.primary.default with the local 'check' glyph in color.text.on-action
- kit choice: the CMP-228 tile's sample frame is 17 time columns × 10 price bands (5 a side, each band the sum of tier ÷ 5 levels), equal-bucket runs drawn as one rect; the stops bucket each band's size
- kit choice: board markers (focus-order numbers, announcements, hidden names, illustrative labels, redline callouts) are drawn in a 1 px color.border.strong outline with a 'board marker' caption — not product UI
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)

## Sources (2)

- spec docs/design/E21/E21-D03.md md5 4f4755b45b309e4f1b11a728ce58dcda at c7b0d2087 (§0 L117); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (54)

- type.ui.caption
- color.text.secondary
- type.num.base
- color.text.primary
- size.icon
- space.inset.xs
- space.inset.sm
- color.surface.sunken
- color.text.tertiary
- border.hairline
- radius.control
- type.ui.body-strong
- color.env.demo
- border.thick
- type.ui.label
- color.surface.raised
- radius.badge
- space.inset.md
- color.surface.canvas
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
- space.stack.xs
- space.dialog.padding
- type.ui.body
- space.inset.lg
- space.stack.sm
- color.border.default
- space.stack.md
- color.heatmap.zero
- color.heatmap.bid.5
- type.ui.heading-sm
- color.border.selected
- color.surface.overlay
- radius.dialog
- color.border.strong
- size.icon.sm
- color.focus.ring
- border.focus
- space.stack.lg
- space.inset.xl
