# E21-D02 / 02 tiers-500-unavailable

File `E21-D02 boards`, page `E21-D02`; export `docs/design/E21/img/E21-D02-02-tiers-500-unavailable.png`; sheet `02-tiers-500-unavailable.json` (validated); theme dark.

Board 02 of 10 (§0 L101: §3 tier strip 50 / 200 / 500; SCR-050/500-unavailable (the option T2); the tier notice). Grid (6400, 0); 3280 x 1947 px; "page E21-D02 · board 02 · r1".

## Frames

- `SCR-050∕streaming · tier 50` (`SCR-050/streaming · tier 50`)
- `SCR-050∕streaming · tier 200` (`SCR-050/streaming · tier 200`)
- `SCR-050∕streaming · tier 500` (`SCR-050/streaming · tier 500`)
- `SCR-050∕500-unavailable` (`SCR-050/500-unavailable`)

## Validator and size

- `02-tiers-500-unavailable.json: 0 errors, 34 warnings, 61 sections, 243703 bytes` (exit 0)
- 61 sections, 1571 shapes, 243703 bytes

## Live checks (11)

- frame 'SCR-050∕streaming · tier 500': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- frame 'SCR-050∕500-unavailable': the depth listbox popup is anchored at the depth control's left edge (x 273, y 42; the kit's estimate 262); if the header relayout moves that control, move the popup with it; never centre it
- frame 'SCR-050∕500-unavailable': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y or its flex parent's alignment — never apply a generic re-centre
- root 'E21-D02 / 02 tiers-500-unavailable' at (6400, 0): read back the name exactly after the first section call; size 3280 x 1947
- after touchTexts + relayout: the root h 1947 is the live check's max(annotation end, footer end 1866) + 80 (the annotation column estimated 1173 px with 15 % slack); re-measure it if the annotations change
- frame 'SCR-050∕streaming · tier 50': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕streaming · tier 200': read back 1280 x 800 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕streaming · tier 500': read back 1280 x 800 at (80, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕500-unavailable': read back 1280 x 800 at (1440, 1016); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D02-02-tiers-500-unavailable.png: record the board id and the PNG size

## Derivations (3)

- tier 50: the extent ends at 63,980 (bids) and 64,040 (asks): the 50th level a side of the seeded book; rows beyond it hold no level and are not drawn; stops ['6.598', '9.017', '11.855', '16.538', '33.324'] BTC (adaptive per tier)
- tier 200: the extent ends at 63,880 (bids) and 64,140 (asks): the 200th level a side of the seeded book; rows beyond it hold no level and are not drawn; stops ['9.089', '11.765', '14.086', '17.242', '28.235'] BTC (adaptive per tier)
- tier 500: the extent ends at 63,680 (bids) and 64,310 (asks): the 500th level a side of the seeded book; rows beyond it hold no level and are not drawn; stops ['9.089', '11.765', '14.086', '17.242', '28.235'] BTC (adaptive per tier)

## Decisions (0)

## Spec gaps (1)

- W-2's example "500 levels per side, showing 63,950–64,120" spans 18 rows at the 10 USDT zoom (§3.1's comfortable "about 18 rows"), but §0 draws the tier strip at compact, where this frame shows 23 rows under the tier notice; no zoom on the 0.10 tick puts 23 rows on 63,950–64,120 (0 fit) and 500 × comfortable is a not-drawn cell (§0): the header keeps W-2's form with the drawn rows (63,910–64,130), the only figure consistent with the ladder; the spec owner to re-figure W-2

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
- W-25 (§12 L453, PROPOSED): "Long 0.30 · entry"
- W-23 (§12 L451, PROPOSED): "3 orders · buy 1.2 BTC"
- spec L258: "BUY MKT"
- spec L258: "SELL MKT"
- spec L259: "FLAT"
- spec L259: "CXL"
- W-22 (§12 L450, verbatim): "Sell 0.5 limit" — the form of "Buy 0.5 limit", its illustrative figures derived from the world
- W-22 (§12 L450, verbatim): "Buy 0.5 limit"
- spec L402: "Depth 200 → 500 · rebuilding"
- W-2 (§12 L430, PROPOSED): "500 levels per side, showing 63,910–64,130" — the form of "500 levels per side, showing 63,950–64,120", its illustrative figures derived from the world
- W-3 (§12 L431, PROPOSED; E09-D09 (A-4)): "The deepest book tier isn't available here."

## Copy gaps (7)

- "depth": kit label, not E21-D02 copy — §2.1's `depth [200 ▾]` slot, its label word
- "Heatmap · time →": kit label, not E21-D02 copy — §2.2's heading words as the pane's label
- "qty": kit label, not E21-D02 copy — `14`:1211's footer label
- "0.10 · 0.25 · 0.50 · 1.0": kit label, not E21-D02 copy — `14`:1211's qty presets (CMP-122); enabled, choosing one sends nothing
- "Detectors": kit label, not E21-D02 copy — the strip's label; CMP-134's words are E25's
- "announced: polite, once": kit label, not E21-D02 copy — board-marker label
- "announced: polite, each press (R-7)": kit label, not E21-D02 copy — board-marker label

## Fallbacks (8)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock and the chevrons
- kit choice: the env badge's icon (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + icon, the colour never the only signal)
- kit choice: the `Ladder │ Table` radiogroup drawn as two 24 px segments, the checked one color.surface.selected with a color.border.selected outline
- kit choice: the heatmap pane draws one row per ladder row (R-2) and one column per trail second (the cell chip's auto = 1 s), equal-stop runs drawn as one rect; compact and comfortable cells keep a 1 px gutter top and bottom, the cosy (`dense`) pane none (§3.1 'the pane's gutters tighter')
- kit choice: CMP-230's glyph (second, after the text) drawn as an 8 px square in color.buy.default or color.sell.default; the words carry the side
- kit choice: the pulled mark's hatch (pattern.hatch.estimated's look, D05E11 §7, cited not re-made) drawn as 2 × 2 steps of color.text.primary on a 6 px 45° track over the pulled cell
- kit choice: board markers (focus-order numbers, announcements, accessible names, redline callouts) are drawn in a 1 px color.border.strong outline — not product UI
- kit choice: menus and the open listbox drawn as color.surface.overlay cards with a 1 px color.border.default outline (popovers over the rows)

## Sources (2)

- spec docs/design/E21/E21-D02.md md5 4d99a14edaaa38680621310731662f6d at the boards PR (§0 L101); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (51)

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
- color.grid.line
- color.heatmap.ask.1
- color.heatmap.ask.2
- color.heatmap.ask.4
- color.heatmap.ask.5
- color.heatmap.ask.3
- color.heatmap.bid.1
- color.heatmap.bid.3
- color.heatmap.bid.2
- color.heatmap.bid.4
- color.surface.app
- color.sell.default
- color.heatmap.bid.5
- color.buy.default
- space.stack.xs
- color.border.strong
- color.status.info.strong
- color.status.info.subtle
- color.focus.ring
- border.focus
- type.ui.body
- color.surface.overlay
- radius.card
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
