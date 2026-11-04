# E19-D04 / 08 gesture-matrix

File `E19-D04 boards`, page `E19-D04`; export `docs/design/E19/img/E19-D04-08-gesture-matrix.png`; sheet `08-gesture-matrix.json` (validated); theme dark.

Board 08 of ten (§0 L78: SCR-038/gesture-matrix-dark, SCR-038/gesture-matrix-light (§5's table and its cursor key)). Grid (15200, 5600); 3280 x 1398 px; "page E19-D04 · board 08 · r1".

## Frames

- `SCR-038∕gesture-matrix-dark` (dark, 1280 x 1200)
- `SCR-038∕gesture-matrix-light` (light, 1280 x 1200)

## Validator and size

- `08-gesture-matrix.json: 0 errors, 1 warnings, 38 sections, 197178 bytes` (exit 0)
- 38 sections, 197178 bytes

## Live checks (6)

- root 'E19-D04 / 08 gesture-matrix' at (15200, 5600): read back the name exactly after the first section call; size 3280 x 1398
- after touchTexts + relayout: the annotation column (estimated 812 px) ends inside the root (h 1398, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕gesture-matrix-dark': read back 1280 x 1200 at (80, 80); clip on, no child spills
- frame 'SCR-038∕gesture-matrix-light': read back 1280 x 1200 at (1440, 80); clip on, no child spills
- export docs/design/E19/img/E19-D04-08-gesture-matrix.png under the dark set; record the board id and the PNG size
- kit reading R-K1: export board 08 a second time under the light set as docs/design/E19/img/E19-D04-08-gesture-matrix-light.png; read back one bound fill (color.surface.raised) as the light value; its '-light' frame is read from that export, its '-dark' frames from docs/design/E19/img/E19-D04-08-gesture-matrix.png

## Readings (0)

## Derivations (1)

- world: BTCUSDT 5m bars from 2026-11-02 00:00 UTC to the clock 2026-11-02 14:30 UTC, one walk seeded 439 (the issue number; drift redrawn every 24 bars), prices at the fixture's tick 0.10, sizes at its qty step 0.001; row size 100 ticks unless a preset says otherwise; the rectangle's price edges are the low / high of the bars it spans

## Spec gaps (0)

## Deviations (0)

## Copy keys (5)

- §5 L237: the header and the sixteen rows' cells, parsed (backticks and bold dropped; the cursor keyword drawn beside its owner)
- "one active tool at a time" (spec L58)
- "identical in DEMO and LIVE" (spec L58)
- "chart.limit_at_price" (spec L246)
- W-31: "Not available here: {command} needs chart trading armed." (spec L351) filled from the world

## Copy gaps (2)

- "Cursor key": the key's heading (kit; §5 names "the cursor key")
- "Gesture-conflict matrix (§5)": the reference frame's heading (kit)

## Fallbacks (1)

- kit stand-in: a CSS cursor (§5's keywords) is drawn as a small shape (crosshair: two 1 px strokes; ew-resize / ns-resize: a bar with two end ticks; grab / grabbing / move / pointer / default: a 10 px glyph box) with its keyword beside it in type.num.sm — the shape is a board marker, the keyword binds

## Sources (8)

- spec E19-D04.md md5 9e0d20c3 in this checkout (§0 L78; BQ ruling RULED, comment 6585044844)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; PR #5517 head; re-pinned when it merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via checkout; merge commit of PR #5487)
- D02E14 E14-D02.md md5 8560e306 at the base 95a625b09
- D07E14 E14-D07.md md5 697232d6 at the base 95a625b09
- D02E17 E17-D02.md md5 cb9a4d78 at the base 95a625b09
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json only (§11: shipped names, nothing new)

## Tokens (18)

- type.ui.caption
- color.text.tertiary
- space.inset.sm
- space.inset.xs
- color.surface.raised
- type.ui.label
- color.text.primary
- border.hairline
- type.num.sm
- color.surface.canvas
- color.text.secondary
- space.stack.xs
- type.ui.heading-sm
- space.inset.xl
- space.stack.lg
- space.inset.lg
- color.surface.app
- space.stack.sm
