# E19-D05 / 09 suppression-matrix

File `E19-D05 boards`, page `E19-D05`; export `docs/design/E19/img/E19-D05-09-suppression-matrix.png`; sheet `09-suppression-matrix.json` (validated); theme light.

Board 09 of ten (§0 L114: SCR-038/suppression-matrix-dark, SCR-038/suppression-matrix-light: §3 with each carrier). Grid (22800, 5600); 2142 x 1302 px; "page E19-D05 · board 09 · r1".

## Frames

- `SCR-038∕suppression-matrix-dark` (dark, 1502 x 512)
- `SCR-038∕suppression-matrix-light` (light, 1502 x 512)

## Validator and size

- `09-suppression-matrix.json: 0 errors, 1 warnings, 24 sections, 62206 bytes` (exit 0)
- 24 sections, 62206 bytes

## Live checks (7)

- root 'E19-D05 / 09 suppression-matrix' at (22800, 5600): read back the name exactly after the first section call; size 2142 x 1302
- after touchTexts + relayout: the annotation column (estimated 538 px) ends inside the root (h 1302, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕suppression-matrix-dark': read back 1502 x 512 at (80, 80); clip on, no child spills
- frame 'SCR-038∕suppression-matrix-light': read back 1502 x 512 at (80, 672); clip on, no child spills
- theme: activate the light token set before exporting board 09; read back one bound fill (color.surface.raised) as the light value
- export docs/design/E19/img/E19-D05-09-suppression-matrix.png; record the board id and the PNG size
- kit reading R-K2: export board 09 a second time under the dark set as docs/design/E19/img/E19-D05-09-suppression-matrix-dark.png; its '-dark' frame is read from that export, its '-light' frame from docs/design/E19/img/E19-D05-09-suppression-matrix.png

## Readings (1)

- R-K1 (export path): §0 names none; the kit takes the merged motion specs' form docs/design/E19/img/E19-D05-NN-<slug>.png (E08-D11 §0)

## Derivations (1)

- world: BTCUSDT 30-minute bars 11 Oct 00:00 – 31 Oct 14:30 UTC (the bar in progress), one upward walk seeded 500 (the issue number, §9's prototype seed), prices at the fixture's tick 0.10, sizes at its qty step 0.001, volume on a 10-tick grain; live updates from 14:41:00 UTC at the 1000 ms default throttle; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (1)

- D02 W-16: "1 s refresh" (spec L425)

## Copy gaps (0)

## Fallbacks (1)

- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen, a timeline or a measurement, never product UI

## Sources (5)

- spec E19-D05.md md5 6cf5556d in this checkout (§0 L114; BQ-13 RULED: ACCEPT; no hand-off file, BQ-1)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; re-pinned when its PR merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via checkout; re-pinned when its PR merges)
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
