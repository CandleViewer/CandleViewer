# E19-D01 / 02 competitive-teardown

File `E19-D01 boards`, page `E19-D01`; export `docs/design/research/img/E19-D01-02-competitive-teardown.png`; sheet `02-competitive-teardown.json` (validated); theme dark.

Board 02 of nine (memo §0 L36: §8 as greyscale schematics redrawn from public text; no vendor screenshot). Grid (7000, 0); 2080 x 1368 px; "page E19-D01 · board 02 · r1".

## Frames

- `competitive∕matrix` (`competitive/matrix`)
- `competitive∕schematics` (`competitive/schematics`)

## Validator and size

- `02-competitive-teardown.json: 0 errors, 0 warnings, 11 sections, 37452 bytes` (exit 0)
- 11 sections, 220 shapes, 37452 bytes

## Live checks (5)

- root 'E19-D01 / 02 competitive-teardown' at (7000, 0): read back the name exactly after the first section call; size 2080 x 1368
- after touchTexts + relayout: the annotation column (estimated 544 px with 15 % slack) ends inside the root (h 1368); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'competitive∕matrix': read back 1440 x 576 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'competitive∕schematics': read back 1440 x 432 at (80, 792); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E19-D01-02-competitive-teardown.png: record the board id and the PNG size

## Derivations (0)

## Decisions (0)

## Spec gaps (0)

## Deviations (1)

- matrix: the three fetched rows' URLs are written as 'public documentation page, fetched <date> (URL in memo §8)' — a board carries no URL (kit rule); the memo keeps the links

## Copy keys (1)

- memo L225: "no word on the chart says developing"

## Copy gaps (3)

- "POC as highlighted blocks; no word on the level": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy) — schematic caption, paraphrasing the quoted vendor words above it
- "IB as a vertical line left of the letters": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy) — schematic caption, paraphrasing the quoted vendor words above it
- "POC line extended until a later bar trades it (a naked-POC ray)": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy) — schematic caption, paraphrasing the quoted vendor words above it

## Fallbacks (2)

- schematic: redrawn from the vendor's public words in greyscale boxes; no vendor screenshot, asset, logo or trade dress (memo §8)
- kit choice: board markers (measurements, reading notes, crossed-out examples) are caption text in a 'dashed · ' outline (board markers, not product UI)

## Sources (3)

- spec (memo) docs/design/research/e19-profiles.md md5 d4e666a3f87a41724547a89a1615d062 at the boards PR (§0 drawn, §13 As built) (§0 L36)
- docs/plan/05-accessibility-standard.md at ca49e693a md5 16c60e646337d48dac83c9fb46f8a239 (`05` §6 profile table: the columns A-6 extends)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (23)

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
- type.ui.label
- type.ui.body
- space.inset.md
- space.stack.sm
- radius.card
- border.hairline
- space.stack.lg
- space.inset.xl
- border.thick
- color.surface.sunken
- space.inset.lg
- radius.control
- type.ui.heading-sm
