# E19-D05 / 01 case-table

File `E19-D05 boards`, page `E19-D05`; export `docs/design/E19/img/E19-D05-01-case-table.png`; sheet `01-case-table.json` (validated); theme dark.

Board 01 of ten (§0 L106: SCR-038/motion-cases-dark: §2's ten rows as a sheet). Grid (0, 0); 2768 x 934 px; "page E19-D05 · board 01 · r1".

## Frames

- `SCR-038∕motion-cases-dark` (dark, 2128 x 736)

## Validator and size

- `01-case-table.json: 0 errors, 0 warnings, 14 sections, 51444 bytes` (exit 0)
- 14 sections, 51444 bytes

## Live checks (4)

- root 'E19-D05 / 01 case-table' at (0, 0): read back the name exactly after the first section call; size 2768 x 934
- after touchTexts + relayout: the annotation column (estimated 428 px) ends inside the root (h 934, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕motion-cases-dark': read back 2128 x 736 at (80, 80); clip on, no child spills
- export docs/design/E19/img/E19-D05-01-case-table.png; record the board id and the PNG size

## Readings (1)

- R-K1 (export path): §0 names none; the kit takes the merged motion specs' form docs/design/E19/img/E19-D05-NN-<slug>.png (E08-D11 §0)

## Derivations (1)

- world: BTCUSDT 30-minute bars 11 Oct 00:00 – 31 Oct 14:30 UTC (the bar in progress), one upward walk seeded 500 (the issue number, §9's prototype seed), prices at the fixture's tick 0.10, sizes at its qty step 0.001, volume on a 10-tick grain; live updates from 14:41:00 UTC at the 1000 ms default throttle; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (1)

- "at 60 Hz": the kit's derived column (PRIM's duration × 60 Hz, as §4.1 counts frames)

## Fallbacks (1)

- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen, a timeline or a measurement, never product UI

## Sources (5)

- spec E19-D05.md md5 3129e693 in this checkout (§0 L106; BQ-13 RULED: ACCEPT; no hand-off file, BQ-1)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; re-pinned when its PR merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via git show 3619e95c5; re-pinned when its PR merges)
- PRIM packages/ui/tokens/primitives.tokens.json md5 b5e47569 (motion durations and easings only)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)

## Tokens (17)

- type.ui.caption
- color.text.primary
- space.inset.sm
- space.inset.xs
- color.surface.canvas
- color.surface.raised
- color.text.tertiary
- type.ui.label
- color.text.secondary
- space.stack.xs
- color.border.strong
- border.hairline
- radius.card
- type.ui.heading-sm
- color.surface.app
- space.stack.sm
- space.inset.lg
