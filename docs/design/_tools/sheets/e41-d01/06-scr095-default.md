# E41-D01 / 06 scr095-default

File `E41-D01 boards`, page `E41-D01`; export `docs/design/E41/img/E41-D01-06-scr095-default.png`; sheet `06-scr095-default.json` (validated); theme dark.

Board 06 of ten (memo §0 L71: SCR-095 default + table view). Grid (0, 5200); 3120 x 1487 px; "page E41-D01 · board 06 · r1".

## Frames

- `SCR-095∕default` (`SCR-095/default`)
- `SCR-095∕table-view` (`SCR-095/table-view`)

## Validator and size

- `06-scr095-default.json: 0 errors, 1 warnings, 61 sections, 162560 bytes` (exit 0)
- 61 sections, 1076 shapes, 162560 bytes

## Live checks (5)

- root 'E41-D01 / 06 scr095-default' at (0, 5200): read back the name exactly after the first section call; size 3120 x 1487
- after touchTexts + relayout: the annotation column (estimated 794 px with 15 % slack) ends inside the root (h 1487); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-095∕default': read back 1200 x 1008 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-095∕table-view': read back 1200 x 1248 at (1360, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E41/img/E41-D01-06-scr095-default.png: record the board id and the PNG size

## Derivations (4)

- LIVE stats over 42: wins 18 (net > 0) → 43 %; expectancy = mean R +0.30R; profit factor = net wins ÷ |net losses| = 1.30; max drawdown −308.33 USDT from the running peak; streaks 4 W / 6 L
- equity: 42 closes, cumulative net +324.57 USDT, peak +632.90 USDT, max drawdown −308.33 USDT (from the running peak)
- R histogram: ≤ −1R 15, −1R to 0R 9, 0R to 1R 4, 1R to 2R 5, ≥ 2R 9 (sum 42 = n)
- table view: equity by close day (30 days); the last cumulative value +324.57 USDT equals the net P&L stat

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (10)

- `14` L2158: "[all v]"
- `14` L2203: "win rate"
- `14` L2203: "expectancy"
- `14` L2211: "profit factor"
- `14` L2211: "max drawdown"
- `14` L2203: "average hold time"
- `14` L2211: "streaks"
- caveat.bucket (§7.1 L163): "Low sample (n = {n})"
- memo L77: ""Export""
- scope.live (§7.1 L160): "LIVE only — DEMO trades are not included"

## Copy gaps (9)

- "Formula": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Equity and drawdown": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "R distribution": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "MAE and MFE": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Performance by": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "A trade with two tags counts in both rows": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "DEMO instead of LIVE": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — WD-2: the toggle switches the scope
- "View as chart": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Next page": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)

## Fallbacks (2)

- lo-fi: charts are drawn from the derived series as rects (bars, steps) and 6 px marks; a scatter's outcome is a shape (win = circle, loss = square), never colour (`14` SCR-095 A11y)
- wireframe: the LIVE / DEMO scope label is words in a bordered badge; color.env.* (hues) is not bound

## Sources (6)

- spec (memo) docs/design/research/e41-journal-review.md md5 f8c849aa9a46a3c9416f197d79eca321 at the boards PR (§0 drawn, §12 As built) (§0 L71)
- docs/design/research/e41-d01-session-protocol.md md5 01433dd72a698bca4453a45f12250544 (the session protocol: stimuli, §4a prompts)
- docs/plan/17-ux-diagrams.md md5 0494186310c960cef92f3c614625db44 (`17` §1.6 journey)
- docs/plan/14-screens-catalogue.md at 46e6acd2d md5 1ca288905451c9e5c495a0468c062641 (`14` SCR-093..096 state words the memo cites)
- docs/plan/21-database-schema.md at 46e6acd2d md5 60a9ee1cef41b27a1f0524190b68f199 (`21` §3.7.2 tag categories)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, ETHUSDT tick 0.01, qty step)

## Tokens (34)

- type.ui.caption
- color.text.secondary
- type.num.md
- color.text.primary
- type.ui.body
- space.inset.sm
- space.stack.xs
- color.surface.raised
- radius.card
- color.border.strong
- type.num.sm
- color.neutral.default
- color.text.tertiary
- color.surface.sunken
- color.border.default
- border.hairline
- type.ui.heading-sm
- type.ui.body-strong
- space.button.paddingX
- space.inset.xs
- radius.control
- space.inset.md
- space.stack.sm
- space.inset.lg
- size.icon
- color.surface.canvas
- radius.badge
- type.ui.heading-md
- type.ui.label
- border.thick
- space.stack.md
- color.surface.app
- space.stack.lg
- space.inset.xl
