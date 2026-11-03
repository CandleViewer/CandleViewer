# E21-D02 / 07 trading-t2-arm-env

File `E21-D02 boards`, page `E21-D02`; export `docs/design/E21/img/E21-D02-07-trading-t2-arm-env.png`; sheet `07-trading-t2-arm-env.json` (validated); theme dark.

Board 07 of 10 (§0 L106: §5 notice and T2 legs, SCR-050/arm-locked, SCR-050/demo, SCR-050/live; ARMED inset). Grid (6400, 3200); 4640 x 2126 px; "page E21-D02 · board 07 · r1".

Light twin: export this board again under the light theme as `docs/design/E21/img/E21-D02-07-trading-t2-arm-env-light.png` (token-bound; §0 dark + light).

## Frames

- `SCR-050∕arm-locked` (`SCR-050/arm-locked`)
- `SCR-050∕demo` (`SCR-050/demo`)
- `SCR-050∕live` (`SCR-050/live`)
- `legs · the one notice` (`legs · the one notice`)
- `inset · ARMED (E30-D04)` (`inset · ARMED (E30-D04)`)

## Validator and size

- `07-trading-t2-arm-env.json: 0 errors, 32 warnings, 68 sections, 241216 bytes` (exit 0)
- 68 sections, 1562 shapes, 241216 bytes

## Live checks (14)

- frame 'SCR-050∕arm-locked': the ⋯ menu is anchored by its right edge 12 px inside the frame's right (x 968, y 42); keep the right edge if its w changes; never centre it
- frame 'SCR-050∕arm-locked': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- frame 'SCR-050∕demo': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- frame 'SCR-050∕live': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y or its flex parent's alignment — never apply a generic re-centre
- light twin: after the dark export, switch to the light theme (wait as the sheets README says) and export the same board as docs/design/E21/img/E21-D02-07-trading-t2-arm-env-light.png
- root 'E21-D02 / 07 trading-t2-arm-env' at (6400, 3200): read back the name exactly after the first section call; size 4640 x 2126
- after touchTexts + relayout: the root h 2126 is the live check's max(annotation end, footer end 2058) + 80 (the annotation column estimated 1192 px with 15 % slack); re-measure it if the annotations change
- frame 'SCR-050∕arm-locked': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕demo': read back 1280 x 800 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕live': read back 1280 x 800 at (2800, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'legs · the one notice': read back 1232 x 992 at (80, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'inset · ARMED (E30-D04)': read back 608 x 176 at (1392, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D02-07-trading-t2-arm-env.png: record the board id and the PNG size

## Derivations (0)

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
- W-20 (§12 L448, PROPOSED; E09-D09 (A-5)): "Orders from here come later; cancel and close work as usual."
- spec L144: "BTCUSDT · Heatmap + Ladder"
- spec L84: "LOCKED"
- spec L152: "Following"
- spec L152: "Pause"
- spec L85: "DEMO"
- spec L151: "Ladder │ Table"
- W-1 (§12 L429, PROPOSED): "DOM ladder, BTCUSDT, DEMO"
- W-22 (§12 L450, verbatim): "Sell 0.5 limit" — the form of "Buy 0.5 limit", its illustrative figures derived from the world
- W-25 (§12 L453, PROPOSED): "Long 0.30 · entry"
- W-23 (§12 L451, PROPOSED): "3 orders · buy 1.2 BTC"
- W-22 (§12 L450, verbatim): "Buy 0.5 limit"
- spec L258: "BUY MKT"
- spec L258: "SELL MKT"
- spec L259: "FLAT"
- spec L259: "CXL"
- W-13 (§12 L441, verbatim): "LOCKED · Acct A · 0.10 BTC"
- spec L230: "DOM ladder, BTCUSDT, LIVE"
- spec L51: "LIVE"
- spec L245: "Read-only while viewing as {user}."
- W-8 (§12 L436, verbatim (PROPOSED there)): "Price feed stale 7 s — market, click and conditional off."

## Copy gaps (14)

- "announced: polite, each press (R-7)": kit label, not E21-D02 copy — board-marker label
- "depth": kit label, not E21-D02 copy — §2.1's `depth [200 ▾]` slot, its label word
- "Heatmap · time →": kit label, not E21-D02 copy — §2.2's heading words as the pane's label
- "qty": kit label, not E21-D02 copy — `14`:1211's footer label
- "0.10 · 0.25 · 0.50 · 1.0": kit label, not E21-D02 copy — `14`:1211's qty presets (CMP-122); enabled, choosing one sends nothing
- "Detectors": kit label, not E21-D02 copy — the strip's label; CMP-134's words are E25's
- "scale": kit label, not E21-D02 copy — §2.1's `scale [log ▾]` slot word
- "trail": kit label, not E21-D02 copy — §2.1's `trail [60 s ▾]` slot word
- "cell": kit label, not E21-D02 copy — §2.1's cell chip (D03E17 §3's words)
- "auto · 1 s": kit label, not E21-D02 copy — the cell chip
- "region name (not on screen)": kit label, not E21-D02 copy — board-marker label
- "the one notice as each leg renders it (rendering 2a)": kit label, not E21-D02 copy — board-marker caption
- "board marker — not product UI": kit label, not E21-D02 copy — board-marker caption
- "ARMED is E30-D04's frame, cited here as an inset and labelled E31; this board draws no ARMED pill (§0: not drawn — the text is binding). dom.arm_toggled is annotated on this inset only; in E21 the toggle sends nothing (§11.1).": kit label, not E21-D02 copy — the inset's citation

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

- spec docs/design/E21/E21-D02.md md5 4d99a14edaaa38680621310731662f6d at the boards PR (§0 L106); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (52)

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
- color.focus.ring
- border.focus
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
- type.ui.body
- color.surface.overlay
- radius.card
- color.env.live
- space.stack.lg
- space.inset.xl
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
