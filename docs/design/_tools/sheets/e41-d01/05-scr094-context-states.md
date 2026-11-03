# E41-D01 / 05 scr094-context-states

File `E41-D01 boards`, page `E41-D01`; export `docs/design/E41/img/E41-D01-05-scr094-context-states.png`; sheet `05-scr094-context-states.json` (validated); theme dark.

Board 05 of ten (memo §0 L70: SCR-094 context states (loading, bar-only, context-not-recorded, pruned, error)). Grid (28000, 0); 3120 x 2263 px; "page E41-D01 · board 05 · r1".

## Frames

- `SCR-094∕loading` (`SCR-094/loading`)
- `SCR-094∕bar-only` (`SCR-094/bar-only`)
- `SCR-094∕context-not-recorded` (`SCR-094/context-not-recorded`)
- `SCR-094∕pruned` (`SCR-094/pruned`)
- `SCR-094∕error` (`SCR-094/error`)

## Validator and size

- `05-scr094-context-states.json: 0 errors, 1 warnings, 43 sections, 107152 bytes` (exit 0)
- 43 sections, 679 shapes, 107152 bytes

## Live checks (8)

- root 'E41-D01 / 05 scr094-context-states' at (28000, 0): read back the name exactly after the first section call; size 3120 x 2263
- after touchTexts + relayout: the annotation column (estimated 911 px with 15 % slack) ends inside the root (h 2263); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-094∕loading': read back 1200 x 616 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-094∕bar-only': read back 1200 x 616 at (1360, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-094∕context-not-recorded': read back 1200 x 528 at (80, 832); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-094∕pruned': read back 1200 x 648 at (1360, 832); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-094∕error': read back 1200 x 544 at (80, 1588); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E41/img/E41-D01-05-scr094-context-states.png: record the board id and the PNG size

## Derivations (13)

- #2051: R = (exit − entry) ÷ (entry − SL) = −1.00R; gross −49.86 USDT, fees 11.57 (0.055 % a side), funding 0.00 USDT, net −61.43 USDT
- title in `14`'s SCR-094 sketch form 'Trade #n SYMBOL side qty (account)': Trade #2051 BTCUSDT Long 0.147 (Account A)
- bar-only: #2031 (2026-10-22 09:52:14 UTC → 10:23:14) spans the recorder's tick gap 10:00–10:40 on 22 Oct; bars exist throughout
- context bars: 19 × 5 min from 09:20 (seeded path through entry 67,685.90, MAE 67,109.20, MFE 68,066.50, exit 67,109.20); high 68,066.50, low 67,089.50
- #2031: R = (exit − entry) ÷ (entry − SL) = −1.00R; gross −49.60 USDT, fees 6.38 (0.055 % a side), funding 0.00 USDT, net −55.98 USDT
- title in `14`'s SCR-094 sketch form 'Trade #n SYMBOL side qty (account)': Trade #2031 BTCUSDT Long 0.086 (Account B)
- not recorded: #2009 opened 2026-10-07 12:59:25 UTC, before recording began 2026-10-08 00:00:00 UTC
- #2009: R = (exit − entry) ÷ (entry − SL) = −1.00R; gross −49.73 USDT, fees 7.74 (0.055 % a side), funding 0.00 USDT, net −57.47 USDT
- title in `14`'s SCR-094 sketch form 'Trade #n SYMBOL side qty (account)': Trade #2009 BTCUSDT Short 0.100 (Account B)
- pruned: #2020 opened 2026-10-15 18:46:30 UTC; ticks before 2026-10-16 00:00:00 UTC are pruned (synthetic retention), bars kept
- context bars: 45 × 5 min from 18:15 (seeded path through entry 2,435.90, MAE 2,445.48, MFE 2,429.95, exit 2,438.43); high 2,446.91, low 2,429.95
- #2020: R = (exit − entry) ÷ (entry − SL) = −0.23R; gross −11.49 USDT, fees 12.17 (0.055 % a side), funding 0.00 USDT, net −23.66 USDT
- title in `14`'s SCR-094 sketch form 'Trade #n SYMBOL side qty (account)': Trade #2020 ETHUSDT Short 4.541 (Account C)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (6)

- `14` L2189: "Open in replay"
- `14` L2189: "Open chart at entry"
- scope.live (§7.1 L160): "LIVE only — DEMO trades are not included"
- context.bars (§7.1 L167): "Bars only for part of this trade — excursions are bar-derived"
- context.none (§7.1 L166): "Context not recorded — fills and prices are listed below"
- context.pruned (§7.1 L168): "Recorded ticks were pruned — bar replay is available"

## Copy gaps (7)

- "Loading market context": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Market context": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Fills": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Back to journal": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — `12` R-181 back link
- "Open bar replay": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Market context could not be loaded": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — no error string in §7.1
- "Retry": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)

## Fallbacks (5)

- fallback: loading skeletons are color.neutral.subtle rects; static (reduced motion); no spinner
- kit choice: a visually hidden string (a chart's text summary for a screen reader, a status) is drawn as caption text in a 'dashed · ' outline
- wireframe: the LIVE / DEMO scope label is words in a bordered badge; color.env.* (hues) is not bound
- lo-fi: the CMP-181 context pane draws bars as hollow / filled rects from the seeded bar path (no candle hue); entry, exit and SL as labelled 1 px rules
- lo-fi: charts are drawn from the derived series as rects (bars, steps) and 6 px marks; a scatter's outcome is a shape (win = circle, loss = square), never colour (`14` SCR-095 A11y)

## Sources (6)

- spec (memo) docs/design/research/e41-journal-review.md md5 b2629298bc1879afa24b935e0d017f5b at the boards PR (§0 drawn, §12 As built) (§0 L70)
- docs/design/research/e41-d01-session-protocol.md md5 01433dd72a698bca4453a45f12250544 (the session protocol: stimuli, §4a prompts)
- docs/plan/17-ux-diagrams.md md5 0494186310c960cef92f3c614625db44 (`17` §1.6 journey)
- docs/plan/14-screens-catalogue.md at 46e6acd2d md5 1ca288905451c9e5c495a0468c062641 (`14` SCR-093..096 state words the memo cites)
- docs/plan/21-database-schema.md at 46e6acd2d md5 60a9ee1cef41b27a1f0524190b68f199 (`21` §3.7.2 tag categories)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, ETHUSDT tick 0.01, qty step)

## Tokens (33)

- radius.card
- color.neutral.subtle
- type.ui.caption
- color.text.tertiary
- color.text.primary
- space.inset.sm
- space.stack.xs
- color.border.strong
- border.hairline
- radius.control
- type.ui.heading-sm
- space.inset.md
- space.stack.sm
- color.surface.raised
- color.text.secondary
- type.num.sm
- space.inset.xs
- color.border.default
- color.surface.canvas
- space.stack.lg
- type.ui.body
- type.ui.heading-md
- type.ui.label
- radius.badge
- border.thick
- space.inset.xl
- space.inset.lg
- space.stack.md
- color.surface.app
- type.ui.body-strong
- size.icon
- color.surface.sunken
- space.button.paddingX
