# E19-D01 / 08 decisions

File `E19-D01 boards`, page `E19-D01`; export `docs/design/research/img/E19-D01-08-decisions.png`; sheet `08-decisions.json` (validated); theme dark.

Board 08 of nine (memo §0 L42: §7 PD-1..PD-8 with each check). Grid (14000, 5200); 2080 x 1912 px; "page E19-D01 · board 08 · r1".

## Frames

- `decisions∕pd-1-to-pd-8` (`decisions/pd-1-to-pd-8`)
- `decisions∕traceability` (`decisions/traceability`)

## Validator and size

- `08-decisions.json: 0 errors, 0 warnings, 14 sections, 53533 bytes` (exit 0)
- 14 sections, 323 shapes, 53533 bytes

## Live checks (5)

- root 'E19-D01 / 08 decisions' at (14000, 5200): read back the name exactly after the first section call; size 2080 x 1912
- after touchTexts + relayout: the annotation column (estimated 494 px with 15 % slack) ends inside the root (h 1912); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'decisions∕pd-1-to-pd-8': read back 1440 x 744 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'decisions∕traceability': read back 1440 x 808 at (80, 960); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E19-D01-08-decisions.png: record the board id and the PNG size

## Derivations (0)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (0)

## Sources (3)

- spec (memo) docs/design/research/e19-profiles.md md5 d4e666a3f87a41724547a89a1615d062 at the boards PR (§0 drawn, §13 As built) (§0 L42)
- docs/plan/05-accessibility-standard.md at ca49e693a md5 16c60e646337d48dac83c9fb46f8a239 (`05` §6 profile table: the columns A-6 extends)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (20)

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
- type.ui.heading-sm
- space.inset.lg
