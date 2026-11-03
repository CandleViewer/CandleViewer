# E19-D01 / 07 density-row-legibility

File `E19-D01 boards`, page `E19-D01`; export `docs/design/research/img/E19-D01-07-density-row-legibility.png`; sheet `07-density-row-legibility.json` (validated); theme dark.

Board 07 of nine (memo §0 L41: §4.3, PD-8: the row ladder at compact and dense, labels on named levels only). Grid (7000, 5200); 3228 x 847 px; "page E19-D01 · board 07 · r1".

## Frames

- `density∕row-ladder` (`density/row-ladder`)
- `density∕compact-docked` (`density/compact-docked`)
- `density∕dense-overlay` (`density/dense-overlay`)

## Validator and size

- `07-density-row-legibility.json: 0 errors, 1 warnings, 19 sections, 72270 bytes` (exit 0)
- 19 sections, 532 shapes, 72270 bytes

## Live checks (6)

- root 'E19-D01 / 07 density-row-legibility' at (7000, 5200): read back the name exactly after the first section call; size 3228 x 847
- after touchTexts + relayout: the annotation column (estimated 826 px with 15 % slack) ends inside the root (h 847); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'density∕row-ladder': read back 1440 x 520 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'density∕compact-docked': read back 494 x 600 at (1600, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'density∕dense-overlay': read back 494 x 600 at (2174, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E19-D01-07-density-row-legibility.png: record the board id and the PNG size

## Derivations (2)

- memo §4.3: px per row, merge factor and the 10 px answer re-derived from each row's Rows (all four agree)
- session 29 Oct · one-tick rows at one-tick rows: 1977 rows over 320 px = 0.16 px each; merge ×13 (`26`: rows < 2 px are summed) → 153 drawn rows of 2.10 px; POC 63,046.1, VA 62,980.0–63,083.6 (one-tick rows)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (3)

- memo L150: "POC 62,974.0" (placeholders filled from the world)
- memo L153: "Value area 70 %"
- memo L56: "Final"

## Copy gaps (3)

- "Row size 1 tick (0.10 USDT), merged ×13 on screen": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy) — PD-8: the row size is in the legend
- "Profile · BTCUSDT": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy)
- "Volume profile": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy)

## Fallbacks (0)

## Sources (3)

- spec (memo) docs/design/research/e19-profiles.md md5 d4e666a3f87a41724547a89a1615d062 at the boards PR (§0 drawn, §13 As built) (§0 L41)
- docs/plan/05-accessibility-standard.md at ca49e693a md5 16c60e646337d48dac83c9fb46f8a239 (`05` §6 profile table: the columns A-6 extends)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (24)

- type.ui.caption
- color.text.secondary
- color.text.tertiary
- space.inset.sm
- space.inset.xs
- color.surface.raised
- color.border.default
- color.text.primary
- color.surface.canvas
- space.stack.xs
- type.ui.body
- space.inset.md
- space.stack.sm
- radius.card
- border.hairline
- type.ui.label
- space.stack.lg
- space.inset.xl
- type.ui.body-strong
- color.surface.sunken
- size.icon
- radius.control
- space.inset.lg
- type.ui.heading-sm
