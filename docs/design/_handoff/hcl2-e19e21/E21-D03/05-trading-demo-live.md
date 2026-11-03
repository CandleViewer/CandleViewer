# E21-D03 / 05 trading-demo-live

File `E21-D03 boards`, page `E21-D03`; export `docs/design/E21/img/E21-D03-05-trading-demo-live.png`; sheet `05-trading-demo-live.json` (validated); theme dark.

Board 05 of 10 (§0 L114: SCR-051/trading-demo, SCR-051/trading-live, SCR-051/live-confirm-off). Grid (25600, 0); 3280 x 1952 px; "page E21-D03 · board 05 · r1".

Light twin: export this board again under the light theme as `docs/design/E21/img/E21-D03-05-trading-demo-live-light.png` (token-bound; §0 dark + light).

## Frames

- `SCR-051∕trading-demo` (`SCR-051/trading-demo`)
- `SCR-051∕trading-live` (`SCR-051/trading-live`)
- `SCR-051∕live-confirm-off` (`SCR-051/live-confirm-off`)

## Validator and size

- `05-trading-demo-live.json: 0 errors, 6 warnings, 30 sections, 101430 bytes` (exit 0)
- 30 sections, 617 shapes, 101430 bytes

## Live checks (7)

- light twin: after the dark export, switch to the light theme (wait as the sheets README says) and export the same board as docs/design/E21/img/E21-D03-05-trading-demo-live-light.png
- root 'E21-D03 / 05 trading-demo-live' at (25600, 0): read back the name exactly after the first section call; size 3280 x 1952
- after touchTexts + relayout: the annotation column (estimated 955 px with 15 % slack) ends inside the root (h 1952); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-051∕trading-demo': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-051∕trading-live': read back 1280 x 800 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-051∕live-confirm-off': read back 1280 x 800 at (80, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D03-05-trading-demo-live.png: record the board id and the PNG size

## Derivations (1)

- SCR-050 behind: 31 rows at compact around mark 64,560.2 (best bid 64,560.2, best ask 64,560.3); cum. depth from the touch; prints = the drop between the last two columns within 6 levels; own orders Buy 0.250 at 64,559.8, Sell 0.100 at 64,560.9

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (24)

- spec L106: "BTCUSDT"
- spec L13: "illustrative, PROPOSED, not a budget"
- spec L30: "DEMO"
- spec L99: "Reset to defaults"
- spec L151: "Reset this tab"
- spec L140: "Cancel"
- spec L5: "Save"
- W-18 (§15 L463, PROPOSED): "LIVE: confirm every market order"
- W-19 (§15 L464, PROPOSED; E30-D04 / E31 (C-14)): "DEMO: market orders send without a confirm"
- spec L175: "Click-trade behaviour"
- W-30 (§15 L475, PROPOSED (adapted)): "Click bid: buy limit · click ask: sell limit · Ctrl+click: market · Shift+click: stop"
- spec L251: "Ctrl+Shift+T = arm/disarm one-click"
- spec L184: "Ask"
- spec L184: "Bid"
- W-1 (§15 L446, verbatim): "Heatmap + Ladder settings"
- W-2 (§15 L447, PROPOSED): "Heatmap + Ladder settings, BTCUSDT, DEMO"
- spec L96: "Depth & scale"
- spec L98: "Colour"
- spec L96: "Ladder"
- spec L97: "Trading"
- spec L121: "Detectors"
- spec L5: "LIVE"
- W-2 (§15 L447, PROPOSED): "Heatmap + Ladder settings, BTCUSDT, LIVE"
- W-20 (§15 L465, PROPOSED; E30-D04 / E31 (C-14)): "Market orders on LIVE will send on one press, with no confirm."

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
- "Quantity presets (BTC)": kit label, not E21-D03 copy — §2.2 names the field "Quantity presets 1–4"; the unit in the label (T A11y)
- "announced: polite, once": kit label, not E21-D03 copy — board-marker label

## Fallbacks (7)

- kit choice: the SCR-050 panel behind the dialog (E21-D02 #440's anatomy) is drawn as context at compact: header, the heatmap pane as run-length cells, the ladder's six columns; its labels are E21-D02's, listed as copy gaps here
- kit choice: the env pill's glyph (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + glyph, the colour never the only signal)
- opacity.scrim is a Tier-1 primitive (validator WARN): the SCR-050 panel behind the modal dialog is dimmed by a color.surface.app rect at opacity.scrim (CMP-043's backdrop)
- kit choice: CMP-006 radios drawn as 16 px circles (1 px color.text.tertiary rest stroke, E05-D04 F-03), the checked one with an 8 px color.action.primary.default dot; CMP-005 checkboxes as 16 px squares, checked filled color.action.primary.default with the local 'check' glyph in color.text.on-action
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the CMP-228 tile's sample frame is 17 time columns × 10 price bands (5 a side, each band the sum of tier ÷ 5 levels), equal-bucket runs drawn as one rect; the stops bucket each band's size
- kit choice: board markers (focus-order numbers, announcements, hidden names, illustrative labels, redline callouts) are drawn in a 1 px color.border.strong outline with a 'board marker' caption — not product UI

## Sources (2)

- spec docs/design/E21/E21-D03.md md5 4f4755b45b309e4f1b11a728ce58dcda at c7b0d2087 (§0 L114); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (55)

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
- size.icon.sm
- type.ui.body
- space.stack.md
- color.heatmap.zero
- color.heatmap.bid.5
- color.border.default
- type.ui.heading-sm
- color.border.selected
- space.inset.lg
- color.surface.overlay
- radius.dialog
- color.env.live
- color.border.strong
- color.focus.ring
- border.focus
- color.status.warning.strong
- color.status.warning.subtle
- space.stack.sm
