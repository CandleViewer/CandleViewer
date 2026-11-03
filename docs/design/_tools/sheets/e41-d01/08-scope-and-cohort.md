# E41-D01 / 08 scope-and-cohort

File `E41-D01 boards`, page `E41-D01`; export `docs/design/E41/img/E41-D01-08-scope-and-cohort.png`; sheet `08-scope-and-cohort.json` (validated); theme dark.

Board 08 of ten (memo §0 L73: environment scope and cohort controls). Grid (14000, 5200); 3120 x 1851 px; "page E41-D01 · board 08 · r1".

## Frames

- `SCR-093∕default · DEMO scope` (`SCR-093/default · DEMO scope`)
- `SCR-095∕default · DEMO toggle on` (`SCR-095/default · DEMO toggle on`)
- `SCR-095∕default · cohort controls` (`SCR-095/default · cohort controls`)

## Validator and size

- `08-scope-and-cohort.json: 0 errors, 3 warnings, 28 sections, 115970 bytes` (exit 0)
- 28 sections, 733 shapes, 115970 bytes

## Live checks (6)

- root 'E41-D01 / 08 scope-and-cohort' at (14000, 5200): read back the name exactly after the first section call; size 3120 x 1851
- after touchTexts + relayout: the annotation column (estimated 790 px with 15 % slack) ends inside the root (h 1851); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-093∕default · DEMO scope': read back 1200 x 744 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-095∕default · DEMO toggle on': read back 1200 x 752 at (1360, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-095∕default · cohort controls': read back 1200 x 752 at (80, 968); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E41/img/E41-D01-08-scope-and-cohort.png: record the board id and the PNG size

## Derivations (8)

- DEMO scope: 12 DEMO trades on Demo 1; no LIVE row and no LIVE figure on the frame
- totals (DEMO, 1 Oct 2026 – 30 Oct 2026 · all accounts): 6 of 12 net-positive → 50 %; mean R +0.39R; net +118.53 USDT (sum of the rows' gross − fees + funding; no aggregate row, WD-9)
- equity: 12 closes, cumulative net +118.53 USDT, peak +125.30 USDT, max drawdown −199.57 USDT (from the running peak)
- R histogram: ≤ −1R 4, −1R to 0R 2, 0R to 1R 0, 1R to 2R 4, ≥ 2R 2 (sum 12 = n)
- DEMO stats over 12: wins 6 (net > 0) → 50 %; expectancy = mean R +0.39R; profit factor = net wins ÷ |net losses| = 1.37; max drawdown −199.57 USDT from the running peak; streaks 4 W / 3 L
- cohort: a Manager granted Account B, Account C sees 25 LIVE trades; Account A is absent from the data and the list (scope, not a control)
- LIVE stats over 25: wins 9 (net > 0) → 36 %; expectancy = mean R −0.02R; profit factor = net wins ÷ |net losses| = 0.76; max drawdown −305.56 USDT from the running peak; streaks 2 W / 5 L
- R histogram: ≤ −1R 11, −1R to 0R 5, 0R to 1R 3, 1R to 2R 3, ≥ 2R 3 (sum 25 = n)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (18)

- `14` L2158: "[all v]"
- memo L77: ""Manage tags""
- memo L77: ""Export""
- scope.demo (§7.1 L161): "DEMO only — LIVE trades are not included"
- `14` L2175: "environment"
- `14` L2158: "range"
- `14` L2154: "account"
- `14` L2168: "symbol"
- `14` L2158: "tag"
- `14` L2175: "outcome"
- caveat.sample (§7.1 L162): "Fewer than 20 trades — statistics are noisy"
- `14` L2203: "win rate"
- `14` L2203: "expectancy"
- `14` L2211: "profit factor"
- `14` L2211: "max drawdown"
- `14` L2203: "average hold time"
- `14` L2211: "streaks"
- scope.live (§7.1 L160): "LIVE only — DEMO trades are not included"

## Copy gaps (6)

- "Next page": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Equity and drawdown": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "R distribution": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Formula": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "DEMO instead of LIVE": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — WD-2: the toggle switches the scope
- "Performance by": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)

## Fallbacks (3)

- wireframe: the LIVE / DEMO scope label is words in a bordered badge; color.env.* (hues) is not bound
- lo-fi: charts are drawn from the derived series as rects (bars, steps) and 6 px marks; a scatter's outcome is a shape (win = circle, loss = square), never colour (`14` SCR-095 A11y)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for the CMP-019 lock glyph

## Sources (6)

- spec (memo) docs/design/research/e41-journal-review.md md5 b2629298bc1879afa24b935e0d017f5b at the boards PR (§0 drawn, §12 As built) (§0 L73)
- docs/design/research/e41-d01-session-protocol.md md5 01433dd72a698bca4453a45f12250544 (the session protocol: stimuli, §4a prompts)
- docs/plan/17-ux-diagrams.md md5 0494186310c960cef92f3c614625db44 (`17` §1.6 journey)
- docs/plan/14-screens-catalogue.md at 46e6acd2d md5 1ca288905451c9e5c495a0468c062641 (`14` SCR-093..096 state words the memo cites)
- docs/plan/21-database-schema.md at 46e6acd2d md5 60a9ee1cef41b27a1f0524190b68f199 (`21` §3.7.2 tag categories)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, ETHUSDT tick 0.01, qty step)

## Tokens (37)

- color.border.strong
- border.hairline
- radius.control
- space.inset.sm
- space.inset.xs
- type.ui.caption
- color.text.tertiary
- color.surface.raised
- color.border.default
- color.text.primary
- type.num.sm
- color.surface.canvas
- type.ui.body-strong
- space.button.paddingX
- type.ui.heading-md
- space.stack.xs
- type.ui.label
- radius.badge
- border.thick
- type.ui.body
- space.stack.sm
- color.text.secondary
- size.icon
- color.surface.sunken
- space.inset.lg
- space.stack.md
- color.surface.app
- space.stack.lg
- space.inset.xl
- space.inset.md
- radius.card
- color.neutral.default
- type.ui.heading-sm
- type.num.md
- color.surface.selected
- size.icon.sm
- color.surface.overlay
