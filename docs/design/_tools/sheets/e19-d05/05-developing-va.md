# E19-D05 / 05 developing-va

File `E19-D05 boards`, page `E19-D05`; export `docs/design/E19/img/E19-D05-05-developing-va.png`; sheet `05-developing-va.json` (validated); theme dark.

Board 05 of ten (§0 L110: SCR-038/developing-va-dark, SCR-038/poc-tie-cap-dark (HS-1 on a tied POC)). Grid (30400, 0); 2848 x 1038 px; "page E19-D05 · board 05 · r1".

## Frames

- `SCR-038∕developing-va-dark` (dark, 800 x 840)
- `SCR-038∕poc-tie-cap-dark` (dark, 1328 x 408)

## Validator and size

- `05-developing-va.json: 0 errors, 0 warnings, 10 sections, 36153 bytes` (exit 0)
- 10 sections, 36153 bytes

## Live checks (5)

- root 'E19-D05 / 05 developing-va' at (30400, 0): read back the name exactly after the first section call; size 2848 x 1038
- after touchTexts + relayout: the annotation column (estimated 594 px) ends inside the root (h 1038, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕developing-va-dark': read back 800 x 840 at (80, 80); clip on, no child spills
- frame 'SCR-038∕poc-tie-cap-dark': read back 1328 x 408 at (960, 80); clip on, no child spills
- export docs/design/E19/img/E19-D05-05-developing-va.png; record the board id and the PNG size

## Readings (2)

- Not drawn — the text is binding (§8.3 L418): D05 W-1's down form "POC {price} ▼ {n} rows" as a legend row and D05 W-1b's down form "POC moved down {n} rows"; the tied POC's two flips appear as text in the intro line only, never as a legend row, and no announcement is drawn here; the down forms are the same strings with the glyph and verb swapped and "up" / "down" as hidden text
- R-K1 (export path): §0 names none; the kit takes the merged motion specs' form docs/design/E19/img/E19-D05-NN-<slug>.png (E08-D11 §0)

## Derivations (3)

- developing VA: as of 14:41 VA 62,500.0 – 62,660.0; the next minute's prints one row under VAL move it to 62,490.0 – 62,650.0 as of 14:42 (POC unchanged at 62,550.0)
- tied POC: 62,550.0 and 62,570.0 alternate on every update at the requested 250 ms for 12 s; HS-1 gives 20 band starts, at most 2 in any 1 s, none from 10 s on
- world: BTCUSDT 30-minute bars 11 Oct 00:00 – 31 Oct 14:30 UTC (the bar in progress), one upward walk seeded 500 (the issue number, §9's prototype seed), prices at the fixture's tick 0.10, sizes at its qty step 0.001, volume on a 10-tick grain; live updates from 14:41:00 UTC at the 1000 ms default throttle; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (12)

- "Session" (D03 L263)
- D03 W-10: "Developing · as of {HH:MM} UTC" (spec L423) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "POC" (spec L53)
- "VAH" (spec L77)
- "VAL" (spec L77)
- "Volume" (spec L10)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "normal" (spec L73)
- "reduce" (spec L60)
- W-1: "POC {price} ▲ {n} rows" (spec L418) filled from the world
- W-1: "POC {price} ▼ {n} rows" (spec L418) filled from the world

## Copy gaps (0)

## Fallbacks (2)

- kit choice: a key frame is a crop of the docked CMP-183 panel (280 px wide, D03's width): a header strip (D02 W-1 and the state word), the plot and the CMP-199 legend's words; D03's controls rows are unchanged by this spec and not repeated
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen, a timeline or a measurement, never product UI

## Sources (5)

- spec E19-D05.md md5 6cf5556d in this checkout (§0 L110; BQ-13 RULED: ACCEPT; no hand-off file, BQ-1)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; re-pinned when its PR merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via checkout; re-pinned when its PR merges)
- PRIM packages/ui/tokens/primitives.tokens.json md5 b5e47569 (motion durations and easings only)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)

## Tokens (20)

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
- space.stack.xs
- space.inset.sm
- color.border.strong
- border.hairline
- radius.card
- type.ui.heading-sm
- color.surface.app
- color.text.tertiary
- space.stack.sm
- space.inset.lg
