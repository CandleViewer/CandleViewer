# E21-D02 / 08 own-orders-detectors

File `E21-D02 boards`, page `E21-D02`; export `docs/design/E21/img/E21-D02-08-own-orders-detectors.png`; sheet `08-own-orders-detectors.json` (validated); theme dark.

Board 08 of 10 (§0 L107: §8 Your orders (single, aggregate, expanded), the position marker, SCR-050/detector-chips). Grid (12800, 3200); 4640 x 1026 px; "page E21-D02 · board 08 · r1".

## Frames

- `SCR-050∕detector-chips` (`SCR-050/detector-chips`)
- `SCR-050∕detector-chips · aggregate expanded` (`SCR-050/detector-chips · aggregate expanded`)
- `SCR-050∕detector-chips · reveal` (`SCR-050/detector-chips · reveal`)

## Validator and size

- `08-own-orders-detectors.json: 0 errors, 38 warnings, 50 sections, 216547 bytes` (exit 0)
- 50 sections, 1407 shapes, 216547 bytes

## Live checks (9)

- frame 'SCR-050∕detector-chips · aggregate expanded': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- frame 'SCR-050∕detector-chips · reveal': the reveal is anchored at x 24, y 404 (beside the 63,960 row); never centre it
- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y or its flex parent's alignment — never apply a generic re-centre
- root 'E21-D02 / 08 own-orders-detectors' at (12800, 3200): read back the name exactly after the first section call; size 4640 x 1026
- after touchTexts + relayout: the root h 1026 is the live check's max(annotation end, footer end 945) + 80 (the annotation column estimated 905 px with 15 % slack); re-measure it if the annotations change
- frame 'SCR-050∕detector-chips': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕detector-chips · aggregate expanded': read back 1280 x 800 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕detector-chips · reveal': read back 1280 x 800 at (2800, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D02-08-own-orders-detectors.png: record the board id and the PNG size

## Derivations (1)

- W-24: the queue ahead of Acct A's order at 63,980 = 12.4 (the level's 14.4 less the own 1.2 and the 0.8 behind)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (28)

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
- W-14 (§12 L442, the ASCII's, "(est.)" C-5): "iceberg 63,970 (estimated)"
- W-15 (§12 L443, the ASCII's, "(est.)" C-5): "stop-run zone 63,900 (estimated)"
- spec L340: "Buy 0.5 limit, account Acct B"
- W-24 (§12 L452, PROPOSED): "ahead 12.4 (estimated)"
- spec L224: "none"

## Copy gaps (11)

- "depth": kit label, not E21-D02 copy — §2.1's `depth [200 ▾]` slot, its label word
- "Heatmap · time →": kit label, not E21-D02 copy — §2.2's heading words as the pane's label
- "qty": kit label, not E21-D02 copy — `14`:1211's footer label
- "0.10 · 0.25 · 0.50 · 1.0": kit label, not E21-D02 copy — `14`:1211's qty presets (CMP-122); enabled, choosing one sends nothing
- "Detectors": kit label, not E21-D02 copy — the strip's label; CMP-134's words are E25's
- "cell name (not on screen)": kit label, not E21-D02 copy — board-marker label
- "63,960 · history, last 60 s": kit label, not E21-D02 copy — the reveal's heading; E21-D04 W-14 words it
- "time": kit label, not E21-D02 copy — the reveal table's column words (E21-D04's CMP-111 reveal)
- "bid resting": kit label, not E21-D02 copy — the reveal table's column words (E21-D04's CMP-111 reveal)
- "ask resting": kit label, not E21-D02 copy — the reveal table's column words (E21-D04's CMP-111 reveal)
- "pulled": kit label, not E21-D02 copy — the reveal table's column words (E21-D04's CMP-111 reveal)

## Fallbacks (8)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock and the chevrons
- kit choice: the env badge's icon (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + icon, the colour never the only signal)
- kit choice: the `Ladder │ Table` radiogroup drawn as two 24 px segments, the checked one color.surface.selected with a color.border.selected outline
- kit choice: the heatmap pane draws one row per ladder row (R-2) and one column per trail second (the cell chip's auto = 1 s), equal-stop runs drawn as one rect; compact and comfortable cells keep a 1 px gutter top and bottom, the cosy (`dense`) pane none (§3.1 'the pane's gutters tighter')
- kit choice: CMP-230's glyph (second, after the text) drawn as an 8 px square in color.buy.default or color.sell.default; the words carry the side
- kit choice: the pulled mark's hatch (pattern.hatch.estimated's look, D05E11 §7, cited not re-made) drawn as 2 × 2 steps of color.text.primary on a 6 px 45° track over the pulled cell
- kit choice: CMP-134 detector chips drawn as pills (radius.pill, a Tier-1 primitive: validator WARN) with a 1 px color.border.default outline, the local 'info' glyph as CMP-227's stand-in and the words in full with "(estimated)"
- kit choice: board markers (focus-order numbers, announcements, accessible names, redline callouts) are drawn in a 1 px color.border.strong outline — not product UI

## Sources (2)

- spec docs/design/E21/E21-D02.md md5 4d99a14edaaa38680621310731662f6d at the boards PR (§0 L107); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (50)

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
- color.status.info.default
- radius.pill
- space.stack.xs
- color.border.strong
- color.status.info.subtle
- color.focus.ring
- border.focus
- type.ui.heading-sm
- space.stack.sm
- radius.card
- space.inset.lg
