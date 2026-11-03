# E21-D03 / 03 colour-cvd-greyscale

File `E21-D03 boards`, page `E21-D03`; export `docs/design/E21/img/E21-D03-03-colour-cvd-greyscale.png`; sheet `03-colour-cvd-greyscale.json` (validated); theme dark.

Board 03 of 10 (§0 L112: SCR-051/colour, SCR-051/cvd-preview, SCR-051/preview-unavailable; the greyscale export). Grid (12800, 0); 3280 x 1952 px; "page E21-D03 · board 03 · r1".

## Frames

- `SCR-051∕colour` (`SCR-051/colour`)
- `SCR-051∕cvd-preview` (`SCR-051/cvd-preview`)
- `SCR-051∕preview-unavailable` (`SCR-051/preview-unavailable`)

## Validator and size

- `03-colour-cvd-greyscale.json: 0 errors, 4 warnings, 45 sections, 132722 bytes` (exit 0)
- 45 sections, 806 shapes, 132722 bytes

## Live checks (6)

- root 'E21-D03 / 03 colour-cvd-greyscale' at (12800, 0): read back the name exactly after the first section call; size 3280 x 1952
- after touchTexts + relayout: the annotation column (estimated 1182 px with 15 % slack) ends inside the root (h 1952); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-051∕colour': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-051∕cvd-preview': read back 1280 x 800 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-051∕preview-unavailable': read back 1280 x 800 at (80, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D03-03-colour-cvd-greyscale.png: record the board id and the PNG size

## Derivations (4)

- SCR-050 behind: 31 rows at compact around mark 64,560.2 (best bid 64,560.2, best ask 64,560.3); cum. depth from the touch; prints = the drop between the last two columns within 6 levels; own orders Buy 0.250 at 64,559.8, Sell 0.100 at 64,560.9
- stop labels 2–5 follow §4's "Stop 1 (BTC)" …
- legend anchors = the tier-200 stops 65.079, 75.468, 90.195, 122.695, 166.134 BTC
- tile name in §2.3's form (L184): "Preview, asks above, bids below: depth 200, log scale, gamma 1.0, CVD-safe palette" + ", simulated deuteranopia" (§4)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (35)

- spec L106: "BTCUSDT"
- spec L13: "illustrative, PROPOSED, not a budget"
- spec L184: "Preview, asks above, bids below: depth 200, log scale, gamma 1.0, standard palette"
- spec L30: "DEMO"
- spec L99: "Reset to defaults"
- spec L151: "Reset this tab"
- spec L140: "Cancel"
- spec L5: "Save"
- spec L165: "Colour scale"
- spec L1: "log"
- spec L165: "linear"
- spec L51: "gamma"
- spec L166: "Scale"
- spec L230: "Adaptive"
- spec L129: "Locked"
- spec L231: "Stop 1 (BTC)"
- spec L167: "Stops"
- spec L21: "Set"
- spec L232: "Standard"
- spec L52: "CVD-safe"
- spec L232: "Convention"
- spec L232: "Green = bid"
- spec L232: "Red = bid"
- W-34 (§15 L479, PROPOSED (the catalogue's words)): "Preview with colour-vision simulation"
- spec L184: "Ask"
- spec L184: "Bid"
- W-1 (§15 L446, verbatim): "Heatmap + Ladder settings"
- W-2 (§15 L447, PROPOSED): "Heatmap + Ladder settings, BTCUSDT, DEMO"
- spec L96: "Depth & scale"
- spec L98: "Colour"
- spec L96: "Ladder"
- spec L97: "Trading"
- spec L121: "Detectors"
- spec L233: "Deuteranopia"
- W-31 (§15 L476, verbatim): "Preview unavailable"

## Copy gaps (14)

- "accessible name (not on screen)": kit label, not E21-D03 copy — board-marker label
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
- "Green = bid · standard set · asks above the mid, bids below": kit label, not E21-D03 copy — CMP-113's words are E21-D04 #504's
- "log scale · stops 65.079 – 166.134 BTC": kit label, not E21-D03 copy — CMP-113's words are E21-D04 #504's
- "Green = bid · CVD-safe set · asks above the mid, bids below": kit label, not E21-D03 copy — CMP-113's words are E21-D04 #504's

## Fallbacks (8)

- kit choice: board markers (focus-order numbers, announcements, hidden names, illustrative labels, redline callouts) are drawn in a 1 px color.border.strong outline with a 'board marker' caption — not product UI
- kit choice: the SCR-050 panel behind the dialog (E21-D02 #440's anatomy) is drawn as context at compact: header, the heatmap pane as run-length cells, the ladder's six columns; its labels are E21-D02's, listed as copy gaps here
- kit choice: the env pill's glyph (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + glyph, the colour never the only signal)
- opacity.scrim is a Tier-1 primitive (validator WARN): the SCR-050 panel behind the modal dialog is dimmed by a color.surface.app rect at opacity.scrim (CMP-043's backdrop)
- kit choice: CMP-006 radios drawn as 16 px circles (1 px color.text.tertiary rest stroke, E05-D04 F-03), the checked one with an 8 px color.action.primary.default dot; CMP-005 checkboxes as 16 px squares, checked filled color.action.primary.default with the local 'check' glyph in color.text.on-action
- kit choice: the stops bar (C-10) is drawn as five color.heatmap.bid.1..5 segments with one 24 × 24 handle box per stop (size.target.min), each beside its CMP-008 input
- kit choice: the CMP-228 tile's sample frame is 17 time columns × 10 price bands (5 a side, each band the sum of tier ÷ 5 levels), equal-bucket runs drawn as one rect; the stops bucket each band's size
- the colour-vision simulation filters the tile only (§4); the board draws the chosen set's tokens and the simulated appearance is cvd_sim.py's render at export, never a drawn colour

## Sources (2)

- spec docs/design/E21/E21-D03.md md5 4f4755b45b309e4f1b11a728ce58dcda at c7b0d2087 (§0 L112); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (61)

- type.ui.caption
- color.text.tertiary
- color.text.primary
- space.stack.xs
- space.inset.sm
- color.surface.canvas
- color.border.strong
- border.hairline
- radius.control
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
- space.inset.lg
- space.stack.sm
- color.heatmap.bid.5
- space.stack.md
- color.heatmap.zero
- color.border.default
- type.ui.heading-sm
- color.border.selected
- color.focus.ring
- border.focus
- color.surface.overlay
- radius.dialog
- color.cvd.heatmap.ask.1
- color.cvd.heatmap.ask.2
- color.cvd.heatmap.ask.3
- color.cvd.heatmap.ask.4
- color.cvd.heatmap.ask.5
- color.cvd.heatmap.bid.1
- color.cvd.heatmap.bid.2
- color.cvd.heatmap.bid.3
- color.cvd.heatmap.bid.4
- color.cvd.heatmap.bid.5
