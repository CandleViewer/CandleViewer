# E21-D02 / 05 stale-disconnected

File `E21-D02 boards`, page `E21-D02`; export `docs/design/E21/img/E21-D02-05-stale-disconnected.png`; sheet `05-stale-disconnected.json` (validated); theme dark.

Board 05 of 10 (§0 L104: SCR-050/stale (T1 and the ≥ T2 step), SCR-050/disconnected). Grid (25600, 0); 4640 x 1026 px; "page E21-D02 · board 05 · r1".

Light twin: export this board again under the light theme as `docs/design/E21/img/E21-D02-05-stale-disconnected-light.png` (token-bound; §0 dark + light).

## Frames

- `SCR-050∕stale` (`SCR-050/stale`)
- `SCR-050∕stale · ≥ T2` (`SCR-050/stale · ≥ T2`)
- `SCR-050∕disconnected` (`SCR-050/disconnected`)

## Validator and size

- `05-stale-disconnected.json: 0 errors, 25 warnings, 49 sections, 215020 bytes` (exit 0)
- 49 sections, 1368 shapes, 215020 bytes

## Live checks (10)

- frame 'SCR-050∕stale': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- frame 'SCR-050∕stale · ≥ T2': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y or its flex parent's alignment — never apply a generic re-centre
- light twin: after the dark export, switch to the light theme (wait as the sheets README says) and export the same board as docs/design/E21/img/E21-D02-05-stale-disconnected-light.png
- root 'E21-D02 / 05 stale-disconnected' at (25600, 0): read back the name exactly after the first section call; size 4640 x 1026
- after touchTexts + relayout: the root h 1026 is the live check's max(annotation end, footer end 945) + 80 (the annotation column estimated 1118 px with 15 % slack); re-measure it if the annotations change
- frame 'SCR-050∕stale': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕stale · ≥ T2': read back 1280 x 800 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕disconnected': read back 1280 x 800 at (2800, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D02-05-stale-disconnected.png: record the board id and the PNG size

## Derivations (3)

- stale age 7 s: last update 00:12:12 at 00:12:19 UTC; T1 2 s, T2 = 3 × T1 = 6 s (§4)
- stale age 15 s: last update 00:12:04 at 00:12:19 UTC; T1 2 s, T2 = 3 × T1 = 6 s (§4)
- disconnected: last data 00:12:15 UTC (W-7's minute)

## Decisions (0)

## Spec gaps (1)

- the T1 frame draws W-5 "Stale 7s" and W-6 "Last update 7 s ago" verbatim (their example age 7 s), yet §4 puts 7 s at ≥ T2 = 3 × T1 = 6 s: the copy deck's figure and §4's thresholds disagree; the frame keeps the T1 treatment (chip, feed.stale) — the spec owner to re-figure W-5 / W-6 or the threshold

## Deviations (0)

## Copy keys (29)

- spec L96: "BTCUSDT"
- spec L160: "mark 64,012.5"
- spec L147: "trail [60 s ▾]"
- spec L224: "T1 (2 s"
- spec L96: "Acct A"
- spec L96: "Acct B"
- spec L348: "pulled 18.0 (estimated)"
- W-5 (§12 L433, verbatim): "Stale 7s"
- W-6 (§12 L434, verbatim): "Last update 7 s ago"
- spec L144: "BTCUSDT · Heatmap + Ladder"
- spec L84: "LOCKED"
- spec L152: "Following"
- spec L152: "Pause"
- spec L85: "DEMO"
- spec L151: "Ladder │ Table"
- W-1 (§12 L429, PROPOSED): "DOM ladder, BTCUSDT, DEMO"
- W-8 (§12 L436, verbatim (PROPOSED there)): "Price feed stale 7 s — market, click and conditional off."
- W-22 (§12 L450, verbatim): "Sell 0.5 limit" — the form of "Buy 0.5 limit", its illustrative figures derived from the world
- W-25 (§12 L453, PROPOSED): "Long 0.30 · entry"
- W-23 (§12 L451, PROPOSED): "3 orders · buy 1.2 BTC"
- W-22 (§12 L450, verbatim): "Buy 0.5 limit"
- spec L258: "BUY MKT"
- spec L258: "SELL MKT"
- spec L259: "FLAT"
- spec L259: "CXL"
- W-26 (§12 L454, verbatim): "Stale 15s"
- W-27 (§12 L455, verbatim (PROPOSED there)): "Price feed stale 15 s — new orders off."
- W-7 (§12 L435, verbatim): "Disconnected — last data 00:12"
- W-9 (§12 L437, verbatim (PROPOSED there)): "Not connected — new orders off; cancel and close still work."

## Copy gaps (8)

- "announced: polite, once on entry": kit label, not E21-D02 copy — board-marker label
- "depth": kit label, not E21-D02 copy — §2.1's `depth [200 ▾]` slot, its label word
- "Heatmap · time →": kit label, not E21-D02 copy — §2.2's heading words as the pane's label
- "qty": kit label, not E21-D02 copy — `14`:1211's footer label
- "0.10 · 0.25 · 0.50 · 1.0": kit label, not E21-D02 copy — `14`:1211's qty presets (CMP-122); enabled, choosing one sends nothing
- "Detectors": kit label, not E21-D02 copy — the strip's label; CMP-134's words are E25's
- "the workspace's one assertive sentence (D02E17:256)": kit label, not E21-D02 copy — the announcement is E17-D02's
- "announced: assertive, once (the workspace's; the panel adds none)": kit label, not E21-D02 copy — board-marker label

## Fallbacks (7)

- kit choice: board markers (focus-order numbers, announcements, accessible names, redline callouts) are drawn in a 1 px color.border.strong outline — not product UI
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock and the chevrons
- kit choice: the env badge's icon (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + icon, the colour never the only signal)
- kit choice: the `Ladder │ Table` radiogroup drawn as two 24 px segments, the checked one color.surface.selected with a color.border.selected outline
- kit choice: the heatmap pane draws one row per ladder row (R-2) and one column per trail second (the cell chip's auto = 1 s), equal-stop runs drawn as one rect; compact and comfortable cells keep a 1 px gutter top and bottom, the cosy (`dense`) pane none (§3.1 'the pane's gutters tighter')
- kit choice: CMP-230's glyph (second, after the text) drawn as an 8 px square in color.buy.default or color.sell.default; the words carry the side
- kit choice: the pulled mark's hatch (pattern.hatch.estimated's look, D05E11 §7, cited not re-made) drawn as 2 × 2 steps of color.text.primary on a 6 px 45° track over the pulled cell

## Sources (2)

- spec docs/design/E21/E21-D02.md md5 4d99a14edaaa38680621310731662f6d at the boards PR (§0 L104); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (49)

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
- type.ui.label
- color.data-confidence.stale.text
- color.data-confidence.stale.surface
- radius.badge
- color.data-confidence.stale.indicator
- type.num.sm
- size.icon.sm
- space.inset.xs
- color.surface.sunken
- color.border.default
- space.button.paddingX
- size.icon
- color.env.demo
- border.thick
- color.surface.raised
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
- color.text.on-action
- color.data-confidence.disconnected.text
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
