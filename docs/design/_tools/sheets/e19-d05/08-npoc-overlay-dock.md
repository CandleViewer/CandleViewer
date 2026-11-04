# E19-D05 / 08 npoc-overlay-dock

File `E19-D05 boards`, page `E19-D05`; export `docs/design/E19/img/E19-D05-08-npoc-overlay-dock.png`; sheet `08-npoc-overlay-dock.json` (validated); theme dark.

Board 08 of ten (§0 L113: SCR-038/npoc-fade-dark, SCR-038/npoc-tested-cut-dark, SCR-038/overlay-show-dark; E15-D14 I-4, I-12, I-20). Grid (15200, 5600); 2928 x 2998 px; "page E19-D05 · board 08 · r1".

## Frames

- `SCR-038∕npoc-fade-dark` (dark, 1408 x 1192)
- `SCR-038∕npoc-tested-cut-dark` (dark, 800 x 752)
- `SCR-038∕overlay-show-dark` (dark, 1104 x 1528)

## Validator and size

- `08-npoc-overlay-dock.json: 0 errors, 1 warnings, 27 sections, 120272 bytes` (exit 0)
- 27 sections, 120272 bytes

## Live checks (6)

- root 'E19-D05 / 08 npoc-overlay-dock' at (15200, 5600): read back the name exactly after the first section call; size 2928 x 2998
- after touchTexts + relayout: the annotation column (estimated 621 px) ends inside the root (h 2998, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕npoc-fade-dark': read back 1408 x 1192 at (80, 80); clip on, no child spills
- frame 'SCR-038∕npoc-tested-cut-dark': read back 800 x 752 at (1568, 80); clip on, no child spills
- frame 'SCR-038∕overlay-show-dark': read back 1104 x 1528 at (80, 1352); clip on, no child spills
- export docs/design/E19/img/E19-D05-08-npoc-overlay-dock.png; record the board id and the PNG size

## Readings (3)

- R-K7: '(pressed)' after D03 W-6 marks the toggle's aria-pressed state on the board (D03 draws a leading CMP-019 check glyph; the crop's legend is words only)
- R-K6: the overlay's DOM legend row mounts in frame 0 as a cut; only the canvas opacity uniform eases (§7.4 names one uniform)
- R-K1 (export path): §0 names none; the kit takes the merged motion specs' form docs/design/E19/img/E19-D05-NN-<slug>.png (E08-D11 §0)

## Derivations (2)

- naked POCs: 8 of the 20 earlier sessions are untested at U0; the nearest 5 are drawn, 3 hidden; at the 15:00 UTC bar close the live bar's run down retests 26 Oct's (62,360.0); 18 Oct's enters the nearest 5 (a cut, §7.2) and the count reads 2
- world: BTCUSDT 30-minute bars 11 Oct 00:00 – 31 Oct 14:30 UTC (the bar in progress), one upward walk seeded 500 (the issue number, §9's prototype seed), prices at the fixture's tick 0.10, sizes at its qty step 0.001, volume on a 10-tick grain; live updates from 14:41:00 UTC at the 1000 ms default throttle; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (16)

- D03 W-10: "Developing · as of {HH:MM} UTC" (spec L423) filled from the world
- D03 W-2: "{k} hidden" (spec L421) filled from the world
- D03 W-6: "Show tested" (D03 L387)
- D03 W-4: "nPOC {date}" (D03 L385) filled from the world
- "Session" (D03 L263)
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "POC" (spec L53)
- "VAL" (spec L77)
- "Volume" (spec L10)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "frame 0" (spec L101)
- "the middle" (spec L101)
- "the end" (spec L77)
- "normal" (spec L73)
- "reduce" (spec L60)
- D03 W-5: "tested" (spec L422)

## Copy gaps (0)

## Fallbacks (3)

- kit choice: a key frame is a crop of the docked CMP-183 panel (280 px wide, D03's width): a header strip (D02 W-1 and the state word), the plot and the CMP-199 legend's words; D03's controls rows are unchanged by this spec and not repeated
- kit stand-in: the renderer binds opacity only to a token and no token carries a key frame's computed opacity (R-3 adds none), so a shape between 0 and 1 is drawn as its outline (1 px border.hairline in its ink, no fill) and its opacity, computed from PRIM's easing at that time, is written in the key frame's caption; 1 is drawn solid and 0 is not drawn
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen, a timeline or a measurement, never product UI

## Sources (5)

- spec E19-D05.md md5 5f60e801 in this checkout (§0 L113; BQ-13 RULED: ACCEPT; no hand-off file, BQ-1)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; re-pinned when its PR merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via git show 3619e95c5; re-pinned when its PR merges)
- PRIM packages/ui/tokens/primitives.tokens.json md5 b5e47569 (motion durations and easings only)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)

## Tokens (23)

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
- space.stack.xs
- space.inset.sm
- color.border.strong
- radius.card
- type.ui.heading-sm
- color.surface.app
- color.text.tertiary
- color.candle.wick
- color.candle.down
- color.candle.up
- space.stack.sm
- space.inset.lg
