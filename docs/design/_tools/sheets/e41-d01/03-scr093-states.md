# E41-D01 / 03 scr093-states

File `E41-D01 boards`, page `E41-D01`; export `docs/design/E41/img/E41-D01-03-scr093-states.png`; sheet `03-scr093-states.json` (validated); theme dark.

Board 03 of ten (memo §0 L68: SCR-093 states (loading, empty, partial, reconciling, no-match, error)). Grid (14000, 0); 3120 x 2827 px; "page E41-D01 · board 03 · r1".

## Frames

- `SCR-093∕loading` (`SCR-093/loading`)
- `SCR-093∕empty` (`SCR-093/empty`)
- `SCR-093∕partial` (`SCR-093/partial`)
- `SCR-093∕reconciling` (`SCR-093/reconciling`)
- `SCR-093∕no-match` (`SCR-093/no-match`)
- `SCR-093∕error` (`SCR-093/error`)
- `SCR-093∕viewer-write-disabled` (`SCR-093/viewer-write-disabled`)

## Validator and size

- `03-scr093-states.json: 0 errors, 11 warnings, 45 sections, 160241 bytes` (exit 0)
- 45 sections, 984 shapes, 160241 bytes

## Live checks (10)

- root 'E41-D01 / 03 scr093-states' at (14000, 0): read back the name exactly after the first section call; size 3120 x 2827
- after touchTexts + relayout: the annotation column (estimated 1063 px with 15 % slack) ends inside the root (h 2827); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-093∕loading': read back 1200 x 544 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-093∕empty': read back 1200 x 416 at (1360, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-093∕partial': read back 1200 x 592 at (80, 760); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-093∕reconciling': read back 1200 x 648 at (1360, 760); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-093∕no-match': read back 1200 x 424 at (80, 1516); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-093∕error': read back 1200 x 376 at (1360, 1516); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-093∕viewer-write-disabled': read back 1200 x 648 at (80, 2048); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E41/img/E41-D01-03-scr093-states.png: record the board id and the PNG size

## Derivations (8)

- empty: 0 LIVE trades close in 1 Sep 2026 – 30 Sep 2026; the first close in the journal is 2026-10-01 16:08:40 UTC
- partial: 9 of the 13 trades closing 1 Oct 2026 – 10 Oct 2026 opened before recording began (2026-10-08 00:00:00 UTC) and carry 'chart context unavailable'
- totals (LIVE, 1 Oct 2026 – 10 Oct 2026 · all accounts): 5 of 13 net-positive → 38 %; mean R +0.09R; net −63.77 USDT (sum of the rows' gross − fees + funding; no aggregate row, WD-9)
- reconciling: the group G-1's 3 legs closed at 2026-10-30 15:07:41 UTC and are drawn as the moment their fills are still arriving
- totals (LIVE, 1 Oct 2026 – 30 Oct 2026 · all accounts): 18 of 42 net-positive → 43 %; mean R +0.30R; net +324.57 USDT (sum of the rows' gross − fees + funding; no aggregate row, WD-9)
- no-match: symbol ETHUSDT with tag late-entry has 0 LIVE trades in 1 Oct 2026 – 30 Oct 2026 (the first empty pair in a fixed order)
- totals (LIVE, 1 Oct 2026 – 30 Oct 2026 · Account A, Account B): 13 of 29 net-positive → 45 %; mean R +0.44R; net +408.45 USDT (sum of the rows' gross − fees + funding; no aggregate row, WD-9)
- Viewer: granted Account A, Account B; 29 LIVE trades; ungranted Account C is absent from the data and the account filter (scope, not a control)

## Decisions (0)

## Spec gaps (1)

- SCR-093 / SCR-094 / SCR-095 / SCR-096 error: §7.1 has no error string; the frames draw a kit label (E41-D02 #1018 / E41-D03 #1081 write it)

## Deviations (0)

## Copy keys (15)

- `14` L2158: "[all v]"
- memo L77: ""Manage tags""
- memo L77: ""Export""
- scope.live (§7.1 L160): "LIVE only — DEMO trades are not included"
- `14` L2175: "environment"
- `14` L2158: "range"
- `14` L2154: "account"
- `14` L2168: "symbol"
- `14` L2158: "tag"
- `14` L2175: "outcome"
- empty.range (§7.1 L164): "No trades in this range"
- `14` L2169: "chart context unavailable"
- `14` L2169: "fills still arriving"
- empty.filter (§7.1 L165): "No trades match these filters"
- memo L142: "Your role can't write in the journal."

## Copy gaps (8)

- "Loading trades": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "The journal starts with the first closed trade, 1 Oct 2026": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — `14`: empty state tied to recording / trading start
- "Reconciling": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Clear filters": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Trades could not be loaded": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — no error string in §7.1
- "Retry": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Apply tag": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Clear selection": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)

## Fallbacks (5)

- fallback: loading skeletons are color.neutral.subtle rects; static (reduced motion); no spinner
- kit choice: a visually hidden string (a chart's text summary for a screen reader, a status) is drawn as caption text in a 'dashed · ' outline
- wireframe: the LIVE / DEMO scope label is words in a bordered badge; color.env.* (hues) is not bound
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for the CMP-019 lock glyph
- kit choice: every disabled T2 control (E09-D09 §2.1) keeps its label, a CMP-019 lock glyph and a dashed color.border.default stroke ('dashed · ' name, dashed by the post-step) where enabled controls have a solid color.border.strong stroke, so the state survives forced colours without the glyph

## Sources (6)

- spec (memo) docs/design/research/e41-journal-review.md md5 74af17cb6110bdf947e812546d1c3e11 at the boards PR (§0 drawn, §12 As built) (§0 L68)
- docs/design/research/e41-d01-session-protocol.md md5 01433dd72a698bca4453a45f12250544 (the session protocol: stimuli, §4a prompts)
- docs/plan/17-ux-diagrams.md md5 0494186310c960cef92f3c614625db44 (`17` §1.6 journey)
- docs/plan/14-screens-catalogue.md at 46e6acd2d md5 1ca288905451c9e5c495a0468c062641 (`14` SCR-093..096 state words the memo cites)
- docs/plan/21-database-schema.md at 46e6acd2d md5 60a9ee1cef41b27a1f0524190b68f199 (`21` §3.7.2 tag categories)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, ETHUSDT tick 0.01, qty step)

## Tokens (35)

- radius.control
- color.neutral.subtle
- space.inset.lg
- space.inset.sm
- color.surface.raised
- color.surface.canvas
- radius.card
- type.ui.caption
- color.text.tertiary
- color.text.primary
- space.stack.xs
- color.border.strong
- border.hairline
- type.ui.body-strong
- space.button.paddingX
- space.inset.xs
- type.ui.heading-md
- type.ui.label
- radius.badge
- border.thick
- type.ui.body
- space.stack.sm
- color.text.secondary
- size.icon
- color.border.default
- color.surface.sunken
- space.stack.md
- color.surface.app
- space.stack.lg
- space.inset.xl
- type.ui.heading-sm
- type.num.sm
- space.inset.md
- size.icon.sm
- color.surface.overlay
