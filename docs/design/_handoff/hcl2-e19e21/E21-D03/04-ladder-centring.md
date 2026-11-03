# E21-D03 / 04 ladder-centring

File `E21-D03 boards`, page `E21-D03`; export `docs/design/E21/img/E21-D03-04-ladder-centring.png`; sheet `04-ladder-centring.json` (validated); theme dark.

Board 04 of 10 (§0 L113: SCR-051/ladder). Grid (19200, 0); 1920 x 1056 px; "page E21-D03 · board 04 · r1".

## Frames

- `SCR-051∕ladder` (`SCR-051/ladder`)

## Validator and size

- `04-ladder-centring.json: 0 errors, 5 warnings, 12 sections, 41359 bytes` (exit 0)
- 12 sections, 236 shapes, 41359 bytes

## Live checks (4)

- root 'E21-D03 / 04 ladder-centring' at (19200, 0): read back the name exactly after the first section call; size 1920 x 1056
- after touchTexts + relayout: the annotation column (estimated 592 px with 15 % slack) ends inside the root (h 1056); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-051∕ladder': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D03-04-ladder-centring.png: record the board id and the PNG size

## Derivations (1)

- SCR-050 behind: 31 rows at compact around mark 64,560.2 (best bid 64,560.2, best ask 64,560.3); cum. depth from the touch; prints = the drop between the last two columns within 6 levels; own orders Buy 0.250 at 64,559.8, Sell 0.100 at 64,560.9

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (28)

- spec L106: "BTCUSDT"
- spec L13: "illustrative, PROPOSED, not a budget"
- spec L30: "DEMO"
- spec L99: "Reset to defaults"
- spec L151: "Reset this tab"
- spec L140: "Cancel"
- spec L5: "Save"
- spec L171: "Auto-follow"
- spec L241: "Free scroll"
- spec L241: "Centre lock"
- W-16 (§15 L461, PROPOSED): "Re-centres on every book update, so the ladder moves constantly."
- spec L172: "Your orders"
- spec L172: "Position"
- spec L54: "Prints"
- spec L172: "Cumulative depth"
- W-17 (§15 L462, PROPOSED): "Queue estimate (estimated)"
- spec L240: "Row height (px)"
- spec L96: "Centring"
- spec L172: "Show"
- spec L184: "Ask"
- spec L184: "Bid"
- W-1 (§15 L446, verbatim): "Heatmap + Ladder settings"
- W-2 (§15 L447, PROPOSED): "Heatmap + Ladder settings, BTCUSDT, DEMO"
- spec L96: "Depth & scale"
- spec L98: "Colour"
- spec L96: "Ladder"
- spec L97: "Trading"
- spec L121: "Detectors"

## Copy gaps (10)

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

## Fallbacks (6)

- kit choice: the SCR-050 panel behind the dialog (E21-D02 #440's anatomy) is drawn as context at compact: header, the heatmap pane as run-length cells, the ladder's six columns; its labels are E21-D02's, listed as copy gaps here
- kit choice: the env pill's glyph (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + glyph, the colour never the only signal)
- opacity.scrim is a Tier-1 primitive (validator WARN): the SCR-050 panel behind the modal dialog is dimmed by a color.surface.app rect at opacity.scrim (CMP-043's backdrop)
- kit choice: CMP-006 radios drawn as 16 px circles (1 px color.text.tertiary rest stroke, E05-D04 F-03), the checked one with an 8 px color.action.primary.default dot; CMP-005 checkboxes as 16 px squares, checked filled color.action.primary.default with the local 'check' glyph in color.text.on-action
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the CMP-228 tile's sample frame is 17 time columns × 10 price bands (5 a side, each band the sum of tier ÷ 5 levels), equal-bucket runs drawn as one rect; the stops bucket each band's size

## Sources (2)

- spec docs/design/E21/E21-D03.md md5 4f4755b45b309e4f1b11a728ce58dcda at c7b0d2087 (§0 L113); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (51)

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
- color.focus.ring
- border.focus
- size.icon.sm
- space.stack.sm
- space.stack.md
- color.heatmap.zero
- color.heatmap.bid.5
- color.border.default
- type.ui.heading-sm
- color.border.selected
- space.inset.lg
- color.surface.overlay
- radius.dialog
