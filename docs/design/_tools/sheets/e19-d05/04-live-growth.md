# E19-D05 / 04 live-growth

File `E19-D05 boards`, page `E19-D05`; export `docs/design/E19/img/E19-D05-04-live-growth.png`; sheet `04-live-growth.json` (validated); theme dark.

Board 04 of ten (§0 L109: SCR-038/growth-120-dark, SCR-038/growth-5000-dark; §4.2's arithmetic). Grid (22800, 0); 3232 x 1534 px; "page E19-D05 · board 04 · r1".

## Frames

- `SCR-038∕growth-120-dark` (dark, 1408 x 1336)
- `SCR-038∕growth-5000-dark` (dark, 1104 x 1240)

## Validator and size

- `04-live-growth.json: 0 errors, 1 warnings, 33 sections, 149883 bytes` (exit 0)
- 33 sections, 149883 bytes

## Live checks (5)

- root 'E19-D05 / 04 live-growth' at (22800, 0): read back the name exactly after the first section call; size 3232 x 1534
- after touchTexts + relayout: the annotation column (estimated 498 px) ends inside the root (h 1534, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕growth-120-dark': read back 1408 x 1336 at (80, 80); clip on, no child spills
- frame 'SCR-038∕growth-5000-dark': read back 1104 x 1240 at (1568, 80); clip on, no child spills
- export docs/design/E19/img/E19-D05-04-live-growth.png; record the board id and the PNG size

## Readings (2)

- R-K5: D02 W-19 has no singular, so the 1-tick row size reads "Row size: 1 ticks (0.1)" as the template gives it (a copy question for E19-D06)
- R-K1 (export path): §0 names none; the kit takes the merged motion specs' form docs/design/E19/img/E19-D05-NN-<slug>.png (E08-D11 §0)

## Derivations (3)

- growth arm: 120 visible rows of 10 ticks around the last price; the prints of U0 → U1 change 6 rows; the scale maximum 15584 is unchanged
- 5 000-row arm: 5000 rows of 1 tick in 360 px = 0.072 px a row < 2 px, so 28 levels merge per drawn row (`26`:238): 179 drawn rows
- world: BTCUSDT 30-minute bars 11 Oct 00:00 – 31 Oct 14:30 UTC (the bar in progress), one upward walk seeded 500 (the issue number, §9's prototype seed), prices at the fixture's tick 0.10, sizes at its qty step 0.001, volume on a 10-tick grain; live updates from 14:41:00 UTC at the 1000 ms default throttle; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (14)

- D03 W-10: "Developing · as of {HH:MM} UTC" (spec L423) filled from the world
- "Session" (D03 L263)
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "VAL" (spec L77)
- "Volume" (spec L10)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "frame 0" (spec L101)
- "the middle" (spec L101)
- "the end" (spec L77)
- "normal" (spec L73)
- "reduce" (spec L60)
- D02 W-20: "Rows merged: {k} levels per row" (D02 L369) filled from the world
- "POC" (spec L53)
- "VAH" (spec L77)

## Copy gaps (0)

## Fallbacks (2)

- kit choice: a key frame is a crop of the docked CMP-183 panel (280 px wide, D03's width): a header strip (D02 W-1 and the state word), the plot and the CMP-199 legend's words; D03's controls rows are unchanged by this spec and not repeated
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen, a timeline or a measurement, never product UI

## Sources (5)

- spec E19-D05.md md5 5f60e801 in this checkout (§0 L109; BQ-13 RULED: ACCEPT; no hand-off file, BQ-1)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; re-pinned when its PR merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via git show 3619e95c5; re-pinned when its PR merges)
- PRIM packages/ui/tokens/primitives.tokens.json md5 b5e47569 (motion durations and easings only)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)

## Tokens (21)

- color.surface.raised
- type.ui.label
- color.text.primary
- color.surface.canvas
- color.profile.bar
- color.profile.valuearea
- color.border.strong
- border.hairline
- type.num.xs
- color.text.secondary
- type.ui.caption
- space.stack.xs
- space.inset.sm
- radius.card
- type.ui.heading-sm
- color.surface.app
- color.profile.poc
- space.inset.xs
- color.text.tertiary
- space.stack.sm
- space.inset.lg
