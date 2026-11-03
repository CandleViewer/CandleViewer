# E41-D01 / 07 scr095-states

File `E41-D01 boards`, page `E41-D01`; export `docs/design/E41/img/E41-D01-07-scr095-states.png`; sheet `07-scr095-states.json` (validated); theme dark.

Board 07 of ten (memo §0 L72: SCR-095 insufficient-sample, low-bucket, empty, no-match, loading, error). Grid (7000, 5200); 3120 x 2343 px; "page E41-D01 · board 07 · r1".

## Frames

- `SCR-095∕insufficient-sample` (`SCR-095/insufficient-sample`)
- `SCR-095∕low-bucket` (`SCR-095/low-bucket`)
- `SCR-095∕empty` (`SCR-095/empty`)
- `SCR-095∕no-match` (`SCR-095/no-match`)
- `SCR-095∕loading` (`SCR-095/loading`)
- `SCR-095∕error` (`SCR-095/error`)

## Validator and size

- `07-scr095-states.json: 0 errors, 1 warnings, 25 sections, 103321 bytes` (exit 0)
- 25 sections, 632 shapes, 103321 bytes

## Live checks (9)

- root 'E41-D01 / 07 scr095-states' at (7000, 5200): read back the name exactly after the first section call; size 3120 x 2343
- after touchTexts + relayout: the annotation column (estimated 841 px with 15 % slack) ends inside the root (h 2343); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-095∕insufficient-sample': read back 1200 x 784 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-095∕low-bucket': read back 1200 x 712 at (1360, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-095∕empty': read back 1200 x 392 at (80, 1000); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-095∕no-match': read back 1200 x 424 at (1360, 1000); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-095∕loading': read back 1200 x 680 at (80, 1532); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-095∕error': read back 1200 x 376 at (1360, 1532); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E41/img/E41-D01-07-scr095-states.png: record the board id and the PNG size

## Derivations (6)

- equity: 12 closes, cumulative net +142.23 USDT, peak +198.53 USDT, max drawdown −137.14 USDT (from the running peak)
- R histogram: ≤ −1R 4, −1R to 0R 2, 0R to 1R 1, 1R to 2R 3, ≥ 2R 2 (sum 12 = n)
- insufficient sample: tag 'range-retest' holds 12 LIVE trades (< 20) in the range — the protocol's 12-trade view
- LIVE stats over 12: wins 6 (net > 0) → 50 %; expectancy = mean R +0.40R; profit factor = net wins ÷ |net losses| = 1.49; max drawdown −137.14 USDT from the running peak; streaks 3 W / 3 L
- low buckets (n < 5) by tag: moved-stop 3, news 3
- LIVE stats over 42: wins 18 (net > 0) → 43 %; expectancy = mean R +0.30R; profit factor = net wins ÷ |net losses| = 1.30; max drawdown −308.33 USDT from the running peak; streaks 4 W / 6 L

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (13)

- `14` L2158: "[all v]"
- caveat.sample (§7.1 L162): "Fewer than 20 trades — statistics are noisy"
- `14` L2203: "win rate"
- `14` L2203: "expectancy"
- `14` L2211: "profit factor"
- `14` L2211: "max drawdown"
- `14` L2203: "average hold time"
- `14` L2211: "streaks"
- memo L77: ""Export""
- scope.live (§7.1 L160): "LIVE only — DEMO trades are not included"
- caveat.bucket (§7.1 L163): "Low sample (n = {n})"
- empty.range (§7.1 L164): "No trades in this range"
- empty.filter (§7.1 L165): "No trades match these filters"

## Copy gaps (11)

- "Cohort: a LIVE subset — LIVE trades tagged 'range-retest', 12 trades (not the DEMO set; board 08 shows DEMO)": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Equity and drawdown": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "R distribution": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Formula": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "DEMO instead of LIVE": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — WD-2: the toggle switches the scope
- "Performance by": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "A trade with two tags counts in both rows": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Clear filters": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Loading analytics": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Analytics could not be loaded": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — no error string in §7.1
- "Retry": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)

## Fallbacks (4)

- lo-fi: charts are drawn from the derived series as rects (bars, steps) and 6 px marks; a scatter's outcome is a shape (win = circle, loss = square), never colour (`14` SCR-095 A11y)
- wireframe: the LIVE / DEMO scope label is words in a bordered badge; color.env.* (hues) is not bound
- kit choice: a visually hidden string (a chart's text summary for a screen reader, a status) is drawn as caption text in a 'dashed · ' outline
- fallback: loading skeletons are color.neutral.subtle rects; static (reduced motion); no spinner

## Sources (6)

- spec (memo) docs/design/research/e41-journal-review.md md5 74af17cb6110bdf947e812546d1c3e11 at the boards PR (§0 drawn, §12 As built) (§0 L72)
- docs/design/research/e41-d01-session-protocol.md md5 01433dd72a698bca4453a45f12250544 (the session protocol: stimuli, §4a prompts)
- docs/plan/17-ux-diagrams.md md5 0494186310c960cef92f3c614625db44 (`17` §1.6 journey)
- docs/plan/14-screens-catalogue.md at 46e6acd2d md5 1ca288905451c9e5c495a0468c062641 (`14` SCR-093..096 state words the memo cites)
- docs/plan/21-database-schema.md at 46e6acd2d md5 60a9ee1cef41b27a1f0524190b68f199 (`21` §3.7.2 tag categories)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, ETHUSDT tick 0.01, qty step)

## Tokens (35)

- type.ui.body-strong
- color.text.primary
- type.ui.body
- color.text.secondary
- space.stack.xs
- size.icon
- space.inset.md
- space.inset.sm
- color.surface.raised
- color.border.strong
- border.hairline
- radius.card
- type.num.sm
- type.ui.caption
- color.neutral.default
- color.text.tertiary
- color.surface.sunken
- color.border.default
- type.ui.heading-sm
- space.button.paddingX
- space.inset.xs
- radius.control
- space.stack.sm
- space.inset.lg
- type.num.md
- radius.badge
- type.ui.heading-md
- type.ui.label
- border.thick
- space.stack.md
- color.surface.app
- space.stack.lg
- color.surface.canvas
- space.inset.xl
- color.neutral.subtle
