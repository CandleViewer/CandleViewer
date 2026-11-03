# E19-D05 / 06 rebucket

File `E19-D05 boards`, page `E19-D05`; export `docs/design/E19/img/E19-D05-06-rebucket.png`; sheet `06-rebucket.json` (validated); theme dark.

Board 06 of ten (§0 L111: SCR-038/rebucket-dark, SCR-038/period-change-dark, SCR-038/feed-break-dark (the contrast case)). Grid (0, 5600); 2928 x 1886 px; "page E19-D05 · board 06 · r1".

## Frames

- `SCR-038∕rebucket-dark` (dark, 1104 x 936)
- `SCR-038∕period-change-dark` (dark, 1104 x 936)
- `SCR-038∕feed-break-dark` (dark, 800 x 672)

## Validator and size

- `06-rebucket.json: 0 errors, 2 warnings, 14 sections, 67505 bytes` (exit 0)
- 14 sections, 67505 bytes

## Live checks (6)

- root 'E19-D05 / 06 rebucket' at (0, 5600): read back the name exactly after the first section call; size 2928 x 1886
- after touchTexts + relayout: the annotation column (estimated 568 px) ends inside the root (h 1886, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕rebucket-dark': read back 1104 x 936 at (80, 80); clip on, no child spills
- frame 'SCR-038∕period-change-dark': read back 1104 x 936 at (1264, 80); clip on, no child spills
- frame 'SCR-038∕feed-break-dark': read back 800 x 672 at (80, 1096); clip on, no child spills
- export docs/design/E19/img/E19-D05-06-rebucket.png; record the board id and the PNG size

## Readings (1)

- R-K1 (export path): §0 names none; the kit takes the merged motion specs' form docs/design/E19/img/E19-D05-NN-<slug>.png (E08-D11 §0)

## Derivations (5)

- re-bucket: row size 100 → 50 ticks from SCR-039: the action at t = 0 (14:41:00 UTC); the busy bar at t = 300 ms (still pending); the result lands at t = 600 ms (synthetic, > 300 ms)
- period change: Fixed range = the last 240 minutes of bars before 14:41:00 UTC (D03's kit choice for a fixed range)
- "Period: Fixed range": the example "Period: {mode}" (spec L78) with this frame's values
- period change: Session → Fixed range (240 minutes): the action at t = 0 (14:41:00 UTC); the busy bar at t = 300 ms (still pending); the result lands at t = 600 ms (synthetic, > 300 ms)
- world: BTCUSDT 30-minute bars 11 Oct 00:00 – 31 Oct 14:30 UTC (the bar in progress), one upward walk seeded 500 (the issue number, §9's prototype seed), prices at the fixture's tick 0.10, sizes at its qty step 0.001, volume on a 10-tick grain; live updates from 14:41:00 UTC at the 1000 ms default throttle; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (13)

- "Session" (D03 L263)
- D02 W-38: "Profile settings applied." (D02 L387)
- D03 W-10: "Developing · as of {HH:MM} UTC" (spec L423) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "POC" (spec L53)
- "VAH" (spec L77)
- "VAL" (spec L77)
- "Volume" (spec L10)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "normal" (spec L73)
- "reduce" (spec L60)
- "Fixed range" (D03 L263)
- D02 W-18: "Stale · last update {HH:MM:SS} UTC" (D02 L367) filled from the world

## Copy gaps (1)

- "visually hidden": the kit's marker label for a string a screen reader hears (board marker)

## Fallbacks (4)

- kit choice: a key frame is a crop of the docked CMP-183 panel (280 px wide, D03's width): a header strip (D02 W-1 and the state word), the plot and the CMP-199 legend's words; D03's controls rows are unchanged by this spec and not repeated
- kit choice: a string a screen reader hears (a polite announcement) is drawn for the board as caption text in a bordered 'visually hidden' box (not on screen in the product)
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen, a timeline or a measurement, never product UI
- opacity.scrim is a Tier-1 primitive (validator WARN); only the CMP-078 stale shade of the contrast case uses it

## Sources (5)

- spec E19-D05.md md5 6cf5556d in this checkout (§0 L111; BQ-13 RULED: ACCEPT; no hand-off file, BQ-1)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; re-pinned when its PR merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via checkout; re-pinned when its PR merges)
- PRIM packages/ui/tokens/primitives.tokens.json md5 b5e47569 (motion durations and easings only)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)

## Tokens (25)

- color.surface.raised
- type.ui.label
- color.text.primary
- color.surface.canvas
- color.profile.bar
- color.profile.valuearea
- color.profile.poc
- type.num.xs
- color.text.secondary
- type.ui.caption
- color.focus.ring
- color.text.tertiary
- space.stack.xs
- space.inset.sm
- color.border.strong
- border.hairline
- radius.control
- color.surface.sunken
- radius.card
- type.ui.heading-sm
- color.surface.app
- opacity.scrim
- color.data-confidence.stale.surface
- space.stack.sm
- space.inset.lg
