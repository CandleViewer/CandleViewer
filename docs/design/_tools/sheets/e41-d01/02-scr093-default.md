# E41-D01 / 02 scr093-default

File `E41-D01 boards`, page `E41-D01`; export `docs/design/E41/img/E41-D01-02-scr093-default.png`; sheet `02-scr093-default.json` (validated); theme dark.

Board 02 of ten (memo §0 L67: SCR-093 default (LIVE scope, columns, totals, paging) + bulk-tag and export-confirm insets). Grid (7000, 0); 3120 x 1595 px; "page E41-D01 · board 02 · r1".

## Frames

- `SCR-093∕default` (`SCR-093/default`)
- `SCR-093∕bulk-tag` (`SCR-093/bulk-tag`)
- `SCR-093∕export` (`SCR-093/export`)

## Validator and size

- `02-scr093-default.json: 0 errors, 4 warnings, 37 sections, 124594 bytes` (exit 0)
- 37 sections, 782 shapes, 124594 bytes

## Live checks (6)

- root 'E41-D01 / 02 scr093-default' at (7000, 0): read back the name exactly after the first section call; size 3120 x 1595
- after touchTexts + relayout: the annotation column (estimated 916 px with 15 % slack) ends inside the root (h 1595); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-093∕default': read back 1200 x 776 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-093∕bulk-tag': read back 1200 x 832 at (1360, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-093∕export': read back 1200 x 416 at (80, 1048); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E41/img/E41-D01-02-scr093-default.png: record the board id and the PNG size

## Derivations (4)

- rows: the 12 newest of 42 LIVE closes, newest first; the trade group G-1 shows one row per account (Account A, Account B, Account C), no aggregate row
- totals (LIVE, 1 Oct 2026 – 30 Oct 2026 · all accounts): 18 of 42 net-positive → 43 %; mean R +0.30R; net +324.57 USDT (sum of the rows' gross − fees + funding; no aggregate row, WD-9)
- bulk-tag: the 3 rows of group G-1 selected; the tag 'late-entry' is already on them, so applying it changes no row (the server answers per row)
- export confirm: 42 rows = the LIVE filter's count; accounts = the accounts present in the rows

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (11)

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
- export.confirm (§7.1 L169): "Includes account data for {accounts} · {env} · {range} · {rows} trades"

## Copy gaps (5)

- "Next page": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Apply tag": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Clear selection": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "format": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Cancel": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)

## Fallbacks (3)

- wireframe: the LIVE / DEMO scope label is words in a bordered badge; color.env.* (hues) is not bound
- wireframe: a primary action is a color.surface.selected fill with a 2 px color.border.strong edge; no action hue
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for the CMP-019 lock glyph

## Sources (6)

- spec (memo) docs/design/research/e41-journal-review.md md5 b2629298bc1879afa24b935e0d017f5b at the boards PR (§0 drawn, §12 As built) (§0 L67)
- docs/design/research/e41-d01-session-protocol.md md5 01433dd72a698bca4453a45f12250544 (the session protocol: stimuli, §4a prompts)
- docs/plan/17-ux-diagrams.md md5 0494186310c960cef92f3c614625db44 (`17` §1.6 journey)
- docs/plan/14-screens-catalogue.md at 46e6acd2d md5 1ca288905451c9e5c495a0468c062641 (`14` SCR-093..096 state words the memo cites)
- docs/plan/21-database-schema.md at 46e6acd2d md5 60a9ee1cef41b27a1f0524190b68f199 (`21` §3.7.2 tag categories)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, ETHUSDT tick 0.01, qty step)

## Tokens (35)

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
- color.surface.selected
- size.icon.sm
- space.dialog.padding
- color.surface.overlay
- radius.dialog
- type.ui.heading-sm
