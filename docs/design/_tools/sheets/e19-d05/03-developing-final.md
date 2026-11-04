# E19-D05 / 03 developing-final

File `E19-D05 boards`, page `E19-D05`; export `docs/design/E19/img/E19-D05-03-developing-final.png`; sheet `03-developing-final.json` (validated); theme light.

Board 03 of ten (§0 L108: SCR-038/developing-final-dark, SCR-038/developing-final-light: the swap, the caps, the emphasis, reduce). Grid (15200, 0); 3536 x 1502 px; "page E19-D05 · board 03 · r1".

## Frames

- `SCR-038∕developing-final-dark` (dark, 1408 x 1304)
- `SCR-038∕developing-final-light` (light, 1408 x 1304)

## Validator and size

- `03-developing-final.json: 0 errors, 1 warnings, 16 sections, 89916 bytes` (exit 0)
- 16 sections, 89916 bytes

## Live checks (7)

- root 'E19-D05 / 03 developing-final' at (15200, 0): read back the name exactly after the first section call; size 3536 x 1502
- after touchTexts + relayout: the annotation column (estimated 604 px) ends inside the root (h 1502, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕developing-final-dark': read back 1408 x 1304 at (80, 80); clip on, no child spills
- frame 'SCR-038∕developing-final-light': read back 1408 x 1304 at (1568, 80); clip on, no child spills
- theme: activate the light token set before exporting board 03; read back one bound fill (color.surface.raised) as the light value
- export docs/design/E19/img/E19-D05-03-developing-final.png; record the board id and the PNG size
- kit reading R-K2: export board 03 a second time under the dark set as docs/design/E19/img/E19-D05-03-developing-final-dark.png; its '-dark' frame is read from that export, its '-light' frame from docs/design/E19/img/E19-D05-03-developing-final.png

## Readings (1)

- R-K1 (export path): §0 names none; the kit takes the merged motion specs' form docs/design/E19/img/E19-D05-NN-<slug>.png (E08-D11 §0)

## Derivations (2)

- developing → final: the 30 Oct session; its last developing recompute as of 23:59 UTC (VA 62,650.0 – 62,800.0), complete at 31 Oct 00:00 UTC (VA 62,650.0 – 62,800.0, POC 62,770.0)
- world: BTCUSDT 30-minute bars 11 Oct 00:00 – 31 Oct 14:30 UTC (the bar in progress), one upward walk seeded 500 (the issue number, §9's prototype seed), prices at the fixture's tick 0.10, sizes at its qty step 0.001, volume on a 10-tick grain; live updates from 14:41:00 UTC at the 1000 ms default throttle; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (14)

- D03 W-10: "Developing · as of {HH:MM} UTC" (spec L423) filled from the world
- D03 W-11: "Final" (spec L424)
- "Session" (D03 L263)
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "POC" (spec L53)
- "VAH" (spec L77)
- "VAL" (spec L77)
- "Volume" (spec L10)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "frame 0" (spec L101)
- "the middle" (spec L101)
- "the end" (spec L77)
- "normal" (spec L73)
- "reduce" (spec L60)

## Copy gaps (1)

- "visually hidden": the kit's marker label for a string a screen reader hears (board marker)

## Fallbacks (4)

- kit choice: a key frame is a crop of the docked CMP-183 panel (280 px wide, D03's width): a header strip (D02 W-1 and the state word), the plot and the CMP-199 legend's words; D03's controls rows are unchanged by this spec and not repeated
- kit stand-in: the renderer binds opacity only to a token and no token carries a key frame's computed opacity (R-3 adds none), so a shape between 0 and 1 is drawn as its outline (1 px border.hairline in its ink, no fill) and its opacity, computed from PRIM's easing at that time, is written in the key frame's caption; 1 is drawn solid and 0 is not drawn
- kit choice: a string a screen reader hears (a polite announcement) is drawn for the board as caption text in a bordered 'visually hidden' box (not on screen in the product)
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen, a timeline or a measurement, never product UI

## Sources (5)

- spec E19-D05.md md5 5f60e801 in this checkout (§0 L108; BQ-13 RULED: ACCEPT; no hand-off file, BQ-1)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; re-pinned when its PR merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via git show 3619e95c5; re-pinned when its PR merges)
- PRIM packages/ui/tokens/primitives.tokens.json md5 b5e47569 (motion durations and easings only)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)

## Tokens (22)

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
- border.hairline
- color.text.tertiary
- space.stack.xs
- space.inset.sm
- color.border.strong
- radius.control
- color.surface.sunken
- radius.card
- type.ui.heading-sm
- color.surface.app
- space.stack.sm
- space.inset.lg
