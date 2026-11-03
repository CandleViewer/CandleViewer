# E21-D02 / 01 anatomy-redlines

File `E21-D02 boards`, page `E21-D02`; export `docs/design/E21/img/E21-D02-01-anatomy-redlines.png`; sheet `01-anatomy-redlines.json` (validated); theme dark.

Board 01 of 10 (§0 L100: §2 at 200 compact (SCR-050/streaming): header, pane, six columns, footer, strip; redlines; SCR-050/free-scroll inset). Grid (0, 0); 3280 x 2139 px; "page E21-D02 · board 01 · r1".

Light twin: export this board again under the light theme as `docs/design/E21/img/E21-D02-01-anatomy-redlines-light.png` (token-bound; §0 dark + light).

## Frames

- `SCR-050∕streaming` (`SCR-050/streaming`)
- `SCR-050∕free-scroll` (`SCR-050/free-scroll`)
- `redlines · token map` (`redlines · token map`)

## Validator and size

- `01-anatomy-redlines.json: 0 errors, 18 warnings, 46 sections, 175245 bytes` (exit 0)
- 46 sections, 1125 shapes, 175245 bytes

## Live checks (10)

- frame 'SCR-050∕streaming': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- frame 'SCR-050∕free-scroll': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y or its flex parent's alignment — never apply a generic re-centre
- light twin: after the dark export, switch to the light theme (wait as the sheets README says) and export the same board as docs/design/E21/img/E21-D02-01-anatomy-redlines-light.png
- root 'E21-D02 / 01 anatomy-redlines' at (0, 0): read back the name exactly after the first section call; size 3280 x 2139
- after touchTexts + relayout: the root h 2139 is the live check's max(annotation end, footer end 2058) + 80 (the annotation column estimated 966 px with 15 % slack); re-measure it if the annotations change
- frame 'SCR-050∕streaming': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕free-scroll': read back 1280 x 800 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'redlines · token map': read back 1280 x 992 at (80, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D02-01-anatomy-redlines.png: record the board id and the PNG size

## Derivations (2)

- streaming at 200 compact: 25 rows 63,890–64,130 at a 10 USDT zoom (bids floor, asks ceil); the mark rule between 64,010 and 64,020; stops ['9.089', '11.765', '14.086', '17.242', '28.235'] BTC (STOP_Q of the window's cells); Cum. depth from the touch; Prints at 64,012.4, 64,012.6, 63,970.0
- free-scroll: the grid scrolled 1 rows up (↑, auto-follow suspended) to the 200 tier's ask end 64,140 (the scroll extent's top)

## Decisions (1)

- the free-scroll inset is drawn as a full 1280 × 800 window (§0's frame size), so the follow slot and the rows read together

## Spec gaps (0)

## Deviations (0)

## Copy keys (27)

- spec L96: "BTCUSDT"
- spec L160: "mark 64,012.5"
- spec L147: "trail [60 s ▾]"
- spec L224: "T1 (2 s"
- spec L96: "Acct A"
- spec L96: "Acct B"
- spec L348: "pulled 18.0 (estimated)"
- W-1 (§12 L429, PROPOSED): "DOM ladder, BTCUSDT, DEMO"
- spec L356: "Heatmap, BTCUSDT, last 60 s, mark 64,012.5"
- spec L144: "BTCUSDT · Heatmap + Ladder"
- spec L84: "LOCKED"
- spec L152: "Following"
- spec L152: "Pause"
- spec L85: "DEMO"
- spec L151: "Ladder │ Table"
- W-20 (§12 L448, PROPOSED; E09-D09 (A-5)): "Orders from here come later; cancel and close work as usual."
- W-22 (§12 L450, verbatim): "Sell 0.5 limit" — the form of "Buy 0.5 limit", its illustrative figures derived from the world
- W-25 (§12 L453, PROPOSED): "Long 0.30 · entry"
- W-23 (§12 L451, PROPOSED): "3 orders · buy 1.2 BTC"
- W-22 (§12 L450, verbatim): "Buy 0.5 limit"
- spec L258: "BUY MKT"
- spec L258: "SELL MKT"
- spec L259: "FLAT"
- spec L259: "CXL"
- W-4 (§12 L432, PROPOSED): "Free scroll — Space to follow"
- spec L152: "Follow"
- W-13 (§12 L441, verbatim): "LOCKED · Acct A · 0.10 BTC"

## Copy gaps (16)

- "region name (not on screen)": kit label, not E21-D02 copy — board-marker label
- "pane role="img" name (not on screen)": kit label, not E21-D02 copy — board-marker label
- "depth": kit label, not E21-D02 copy — §2.1's `depth [200 ▾]` slot, its label word
- "Heatmap · time →": kit label, not E21-D02 copy — §2.2's heading words as the pane's label
- "qty": kit label, not E21-D02 copy — `14`:1211's footer label
- "0.10 · 0.25 · 0.50 · 1.0": kit label, not E21-D02 copy — `14`:1211's qty presets (CMP-122); enabled, choosing one sends nothing
- "Detectors": kit label, not E21-D02 copy — the strip's label; CMP-134's words are E25's
- "announced: polite, once": kit label, not E21-D02 copy — board-marker label
- "compact": kit label, not E21-D02 copy — density word of `16`
- "comfortable": kit label, not E21-D02 copy — density word of `16`
- "scale": kit label, not E21-D02 copy — §2.1's `scale [log ▾]` slot word
- "trail": kit label, not E21-D02 copy — §2.1's `trail [60 s ▾]` slot word
- "cell": kit label, not E21-D02 copy — §2.1's cell chip (D03E17 §3's words)
- "auto · 1 s": kit label, not E21-D02 copy — the cell chip
- "⋯ open: scale, trail, cell and ARM (§2.1's overflow order)": kit label, not E21-D02 copy — board-marker caption
- "board marker — not product UI": kit label, not E21-D02 copy — board-marker caption

## Fallbacks (8)

- kit choice: board markers (focus-order numbers, announcements, accessible names, redline callouts) are drawn in a 1 px color.border.strong outline — not product UI
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock and the chevrons
- kit choice: the env badge's icon (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + icon, the colour never the only signal)
- kit choice: the `Ladder │ Table` radiogroup drawn as two 24 px segments, the checked one color.surface.selected with a color.border.selected outline
- kit choice: the heatmap pane draws one row per ladder row (R-2) and one column per trail second (the cell chip's auto = 1 s), equal-stop runs drawn as one rect; compact and comfortable cells keep a 1 px gutter top and bottom, the cosy (`dense`) pane none (§3.1 'the pane's gutters tighter')
- kit choice: CMP-230's glyph (second, after the text) drawn as an 8 px square in color.buy.default or color.sell.default; the words carry the side
- kit choice: the pulled mark's hatch (pattern.hatch.estimated's look, D05E11 §7, cited not re-made) drawn as 2 × 2 steps of color.text.primary on a 6 px 45° track over the pulled cell
- kit choice: menus and the open listbox drawn as color.surface.overlay cards with a 1 px color.border.default outline (popovers over the rows)

## Sources (2)

- spec docs/design/E21/E21-D02.md md5 4d99a14edaaa38680621310731662f6d at the boards PR (§0 L100); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (50)

- type.ui.caption
- color.text.tertiary
- color.text.primary
- space.stack.xs
- space.inset.sm
- color.surface.canvas
- color.border.strong
- border.hairline
- radius.control
- type.ui.body-strong
- color.text.secondary
- type.num.sm
- size.icon.sm
- space.inset.xs
- color.surface.sunken
- color.border.default
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
- type.ui.body
- color.surface.overlay
- radius.card
- space.stack.sm
- space.stack.lg
- space.inset.xl
- type.ui.heading-sm
- space.inset.lg
