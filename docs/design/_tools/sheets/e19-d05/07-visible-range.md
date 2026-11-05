# E19-D05 / 07 visible-range

File `E19-D05 boards`, page `E19-D05`; export `docs/design/E19/img/E19-D05-07-visible-range.png`; sheet `07-visible-range.json` (validated); theme dark.

Board 07 of ten (§0 L112: SCR-038/visible-range-pan-dark, SCR-038/visible-range-settle-dark). Grid (7600, 5600); 3232 x 1054 px; "page E19-D05 · board 07 · r1".

## Frames

- `SCR-038∕visible-range-pan-dark` (dark, 1408 x 856)
- `SCR-038∕visible-range-settle-dark` (dark, 1104 x 752)

## Validator and size

- `07-visible-range.json: 0 errors, 0 warnings, 11 sections, 55776 bytes` (exit 0)
- 11 sections, 55776 bytes

## Live checks (5)

- root 'E19-D05 / 07 visible-range' at (7600, 5600): read back the name exactly after the first section call; size 3232 x 1054
- after touchTexts + relayout: the annotation column (estimated 485 px) ends inside the root (h 1054, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕visible-range-pan-dark': read back 1408 x 856 at (80, 80); clip on, no child spills
- frame 'SCR-038∕visible-range-settle-dark': read back 1104 x 752 at (1568, 80); clip on, no child spills
- export docs/design/E19/img/E19-D05-07-visible-range.png; record the board id and the PNG size

## Readings (1)

- R-K1 (export path): §0 names none; the kit takes the merged motion specs' form docs/design/E19/img/E19-D05-NN-<slug>.png (E08-D11 §0)

## Derivations (3)

- pan: 24 bars visible, one bar further back per pointer step; recomputes at 0 ms, 100 ms, 200 ms, 300 ms (≤ 10 Hz); POC 62,550.0 → 62,550.0 → 62,640.0 → 62,650.0
- settle: pointer released at 350 ms, one bar past the last throttled recompute; the debounce (100 ms, C-4) recomputes at 450 ms: POC 62,650.0, VA 62,540.0 – 62,690.0
- world: BTCUSDT 30-minute bars 11 Oct 00:00 – 31 Oct 14:30 UTC (the bar in progress), one upward walk seeded 500 (the issue number, §9's prototype seed), prices at the fixture's tick 0.10, sizes at its qty step 0.001, volume on a 10-tick grain; live updates from 14:41:00 UTC at the 1000 ms default throttle; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (10)

- "Visible range" (D03 L263)
- D03 W-10: "Developing · as of {HH:MM} UTC" (spec L423) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "POC" (spec L53)
- "VAH" (spec L77)
- "VAL" (spec L77)
- "Volume" (spec L10)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "normal" (spec L73)
- "reduce" (spec L60)

## Copy gaps (0)

## Fallbacks (2)

- kit choice: a key frame is a crop of the docked CMP-183 panel (280 px wide, D03's width): a header strip (D02 W-1 and the state word), the plot and the CMP-199 legend's words; D03's controls rows are unchanged by this spec and not repeated
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen, a timeline or a measurement, never product UI

## Sources (5)

- spec E19-D05.md md5 3129e693 in this checkout (§0 L112; BQ-13 RULED: ACCEPT; no hand-off file, BQ-1)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; re-pinned when its PR merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via git show 3619e95c5; re-pinned when its PR merges)
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
