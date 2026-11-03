# E21-D02 / 09 legend-greyscale-cvd

File `E21-D02 boards`, page `E21-D02`; export `docs/design/E21/img/E21-D02-09-legend-greyscale-cvd.png`; sheet `09-legend-greyscale-cvd.json` (validated); theme dark.

Board 09 of 10 (§0 L108: §7 legend, the greyscale and the three simulated exports of board 01). Grid (19200, 3200); 3184 x 1787 px; "page E21-D02 · board 09 · r1".

## Frames

- `SCR-050∕streaming · CVD twin set` (`SCR-050/streaming · CVD twin set`)
- `legend · contrast · forced colours` (`legend · contrast · forced colours`)
- `exports · greyscale and simulations` (`exports · greyscale and simulations`)

## Validator and size

- `09-legend-greyscale-cvd.json: 0 errors, 9 warnings, 34 sections, 126026 bytes` (exit 0)
- 34 sections, 798 shapes, 126026 bytes

## Live checks (7)

- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y or its flex parent's alignment — never apply a generic re-centre
- root 'E21-D02 / 09 legend-greyscale-cvd' at (19200, 3200): read back the name exactly after the first section call; size 3184 x 1787
- after touchTexts + relayout: the root h 1787 is the live check's max(annotation end, footer end 1706) + 80 (the annotation column estimated 635 px with 15 % slack); re-measure it if the annotations change
- frame 'SCR-050∕streaming · CVD twin set': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'legend · contrast · forced colours': read back 1184 x 784 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'exports · greyscale and simulations': read back 1008 x 640 at (80, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D02-09-legend-greyscale-cvd.png: record the board id and the PNG size

## Derivations (1)

- legend anchors: 0, the middle stop's lower edge 14.086 and the window's largest cell 41.595 BTC (§7.2's form: '0', '25', '120 BTC')

## Decisions (0)

## Spec gaps (1)

- §0 / §7.3: three simulated exports, but cvd_sim.py writes greyscale, deuteranopia and protanopia only: tritanopia has no image tool, so §7.3's computed tritanopia ΔE stands for it

## Deviations (0)

## Copy keys (26)

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
- W-20 (§12 L448, PROPOSED; E09-D09 (A-5)): "Orders from here come later; cancel and close work as usual."
- W-22 (§12 L450, verbatim): "Sell 0.5 limit" — the form of "Buy 0.5 limit", its illustrative figures derived from the world
- W-25 (§12 L453, PROPOSED): "Long 0.30 · entry"
- W-23 (§12 L451, PROPOSED): "3 orders · buy 1.2 BTC"
- W-22 (§12 L450, verbatim): "Buy 0.5 limit"
- spec L258: "BUY MKT"
- spec L258: "SELL MKT"
- spec L259: "FLAT"
- spec L259: "CXL"
- spec L287: "Bid: resting buy liquidity, left column, below the best price"
- spec L287: "Ask: resting sell liquidity, right column, above the best price"
- spec L5: "log"

## Copy gaps (12)

- "depth": kit label, not E21-D02 copy — §2.1's `depth [200 ▾]` slot, its label word
- "Heatmap · time →": kit label, not E21-D02 copy — §2.2's heading words as the pane's label
- "qty": kit label, not E21-D02 copy — `14`:1211's footer label
- "0.10 · 0.25 · 0.50 · 1.0": kit label, not E21-D02 copy — `14`:1211's qty presets (CMP-122); enabled, choosing one sends nothing
- "Detectors": kit label, not E21-D02 copy — the strip's label; CMP-134's words are E25's
- "scale: log": kit label, not E21-D02 copy — the legend's scale word
- "Side, three ways (§7.1): the column (Bid left of Ask), the B / A letter, the colour; in the pane bids sit below the mark and asks above": kit label, not E21-D02 copy — board-marker caption
- "board marker — not product UI": kit label, not E21-D02 copy — board-marker caption
- "docs/design/E21/img/E21-D02-01-anatomy-redlines.png → docs/design/E21/img/E21-D02-01-anatomy-redlines-greyscale.png": kit label, not E21-D02 copy — the export names cvd_sim.py writes
- "docs/design/E21/img/E21-D02-01-anatomy-redlines.png → docs/design/E21/img/E21-D02-01-anatomy-redlines-deuteranopia.png": kit label, not E21-D02 copy — the export names cvd_sim.py writes
- "docs/design/E21/img/E21-D02-01-anatomy-redlines.png → docs/design/E21/img/E21-D02-01-anatomy-redlines-protanopia.png": kit label, not E21-D02 copy — the export names cvd_sim.py writes
- "Made at export by docs/design/_tools/cvd_sim.py from board 01's dark export (a filter, never a drawn colour):": kit label, not E21-D02 copy — board-marker caption

## Fallbacks (7)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock and the chevrons
- kit choice: the env badge's icon (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + icon, the colour never the only signal)
- kit choice: the `Ladder │ Table` radiogroup drawn as two 24 px segments, the checked one color.surface.selected with a color.border.selected outline
- kit choice: the heatmap pane draws one row per ladder row (R-2) and one column per trail second (the cell chip's auto = 1 s), equal-stop runs drawn as one rect; compact and comfortable cells keep a 1 px gutter top and bottom, the cosy (`dense`) pane none (§3.1 'the pane's gutters tighter')
- kit choice: CMP-230's glyph (second, after the text) drawn as an 8 px square in color.buy.default or color.sell.default; the words carry the side
- kit choice: the pulled mark's hatch (pattern.hatch.estimated's look, D05E11 §7, cited not re-made) drawn as 2 × 2 steps of color.text.primary on a 6 px 45° track over the pulled cell
- kit choice: board markers (focus-order numbers, announcements, accessible names, redline callouts) are drawn in a 1 px color.border.strong outline — not product UI

## Sources (2)

- spec docs/design/E21/E21-D02.md md5 4d99a14edaaa38680621310731662f6d at the boards PR (§0 L108); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (56)

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
- color.heatmap.zero
- color.cvd.heatmap.ask.1
- color.cvd.heatmap.ask.2
- color.cvd.heatmap.ask.3
- color.grid.line
- color.cvd.heatmap.ask.4
- color.cvd.heatmap.ask.5
- color.sell.default
- color.cvd.heatmap.bid.2
- color.cvd.heatmap.bid.1
- color.cvd.heatmap.bid.3
- color.cvd.heatmap.bid.4
- color.cvd.heatmap.bid.5
- color.buy.default
- color.surface.app
- color.heatmap.bid.1
- color.heatmap.bid.2
- color.heatmap.bid.3
- color.heatmap.bid.4
- color.heatmap.bid.5
- color.heatmap.ask.1
- color.heatmap.ask.2
- color.heatmap.ask.3
- color.heatmap.ask.4
- color.heatmap.ask.5
- space.inset.lg
- space.stack.xs
- radius.card
- space.stack.lg
- space.inset.xl
- type.ui.heading-sm
- space.stack.sm
