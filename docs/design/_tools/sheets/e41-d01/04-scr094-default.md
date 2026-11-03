# E41-D01 / 04 scr094-default

File `E41-D01 boards`, page `E41-D01`; export `docs/design/E41/img/E41-D01-04-scr094-default.png`; sheet `04-scr094-default.json` (validated); theme dark.

Board 04 of ten (memo §0 L69: SCR-094 default (fills, excursions, attribution, siblings, notes, tags, replay link)). Grid (21000, 0); 1840 x 1356 px; "page E41-D01 · board 04 · r1".

## Frames

- `SCR-094∕default` (`SCR-094/default`)

## Validator and size

- `04-scr094-default.json: 0 errors, 9 warnings, 10 sections, 49920 bytes` (exit 0)
- 10 sections, 283 shapes, 49920 bytes

## Live checks (4)

- root 'E41-D01 / 04 scr094-default' at (21000, 0): read back the name exactly after the first section call; size 1840 x 1356
- after touchTexts + relayout: the annotation column (estimated 794 px with 15 % slack) ends inside the root (h 1356); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-094∕default': read back 1200 x 1104 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E41/img/E41-D01-04-scr094-default.png: record the board id and the PNG size

## Derivations (5)

- #2051: R = (exit − entry) ÷ (entry − SL) = −1.00R; gross −49.86 USDT, fees 11.57 (0.055 % a side), funding 0.00 USDT, net −61.43 USDT
- context bars: 20 × 5 min from 14:00 (seeded path through entry 71,708.20, MAE 71,369.00, MFE 71,874.40, exit 71,369.00); high 71,874.40, low 71,348.60
- group G-1: 3 legs, one per account, same prices; no aggregate row and no group sum is drawn (WD-9)
- title in `14`'s SCR-094 sketch form 'Trade #n SYMBOL side qty (account)': Trade #2051 BTCUSDT Long 0.147 (Account A)
- opened from SCR-093: yesterday's loser #2051 (Account A's leg of G-1), stopped at −1.00R

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (4)

- `14` L2189: "Open in replay"
- `14` L2189: "Open chart at entry"
- scope.live (§7.1 L160): "LIVE only — DEMO trades are not included"
- memo L142: "Your role can't write in the journal."

## Copy gaps (8)

- "Fills": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Who acted": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Market context": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Trade group": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Note": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Add tag": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Removing an auto tag is recorded (journal.tag_removed)": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Back to journal": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — `12` R-181 back link

## Fallbacks (5)

- lo-fi: the CMP-181 context pane draws bars as hollow / filled rects from the seeded bar path (no candle hue); entry, exit and SL as labelled 1 px rules
- lo-fi: charts are drawn from the derived series as rects (bars, steps) and 6 px marks; a scatter's outcome is a shape (win = circle, loss = square), never colour (`14` SCR-095 A11y)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for the CMP-019 lock glyph
- wireframe: the LIVE / DEMO scope label is words in a bordered badge; color.env.* (hues) is not bound
- kit choice: every disabled T2 control (E09-D09 §2.1) keeps its label, a CMP-019 lock glyph and a dashed color.border.default stroke ('dashed · ' name, dashed by the post-step) where enabled controls have a solid color.border.strong stroke, so the state survives forced colours without the glyph

## Sources (6)

- spec (memo) docs/design/research/e41-journal-review.md md5 f8c849aa9a46a3c9416f197d79eca321 at the boards PR (§0 drawn, §12 As built) (§0 L69)
- docs/design/research/e41-d01-session-protocol.md md5 01433dd72a698bca4453a45f12250544 (the session protocol: stimuli, §4a prompts)
- docs/plan/17-ux-diagrams.md md5 0494186310c960cef92f3c614625db44 (`17` §1.6 journey)
- docs/plan/14-screens-catalogue.md at 46e6acd2d md5 1ca288905451c9e5c495a0468c062641 (`14` SCR-093..096 state words the memo cites)
- docs/plan/21-database-schema.md at 46e6acd2d md5 60a9ee1cef41b27a1f0524190b68f199 (`21` §3.7.2 tag categories)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, ETHUSDT tick 0.01, qty step)

## Tokens (35)

- type.ui.caption
- color.text.secondary
- type.num.sm
- color.text.primary
- space.inset.sm
- space.stack.xs
- color.text.tertiary
- space.inset.xs
- color.surface.raised
- color.border.default
- color.surface.canvas
- space.stack.lg
- border.hairline
- color.surface.sunken
- type.ui.heading-sm
- type.ui.body-strong
- space.button.paddingX
- radius.control
- color.border.strong
- type.ui.body
- space.inset.md
- space.stack.sm
- radius.card
- type.ui.label
- size.icon.sm
- color.surface.hover
- type.ui.heading-md
- radius.badge
- border.thick
- space.inset.xl
- space.inset.lg
- space.stack.md
- color.surface.app
- color.surface.overlay
- color.border.subtle
