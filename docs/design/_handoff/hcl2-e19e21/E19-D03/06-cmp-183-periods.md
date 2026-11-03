# E19-D03 / 06 cmp-183-periods

File `E19-D03 boards`, page `E19-D03`; export `docs/design/E19/img/E19-D03-06-cmp-183-periods.png`; sheet `06-cmp-183-periods.json` (validated); theme dark.

Board 06 of ten (§0 L79: CMP-183 ref frames (the five period words); SCR-038/developing-dark, SCR-038/final-dark, SCR-038/approximated-dark, SCR-038/partial-dark, SCR-038/edge-5000-rows-dark). Grid (0, 5600); 3280 x 3416 px; "page E19-D03 · board 06 · r1".

## Frames

- `CMP-183 · VolumeProfilePane — ref frame (Session)` (dark, 360 x 560)
- `CMP-183 · VolumeProfilePane — ref frame (Fixed range)` (dark, 360 x 560)
- `CMP-183 · VolumeProfilePane — ref frame (Visible range)` (dark, 360 x 560)
- `CMP-183 · VolumeProfilePane — ref frame (Anchored)` (dark, 360 x 560)
- `CMP-183 · VolumeProfilePane — ref frame (Composite)` (dark, 360 x 560)
- `SCR-038∕developing-dark` (dark, 1280 x 800)
- `SCR-038∕final-dark` (dark, 1280 x 800)
- `SCR-038∕approximated-dark` (dark, 1280 x 800)
- `SCR-038∕partial-dark` (dark, 1280 x 800)
- `SCR-038∕edge-5000-rows-dark` (dark, 1280 x 800)

## Validator and size

- `06-cmp-183-periods.json: 0 errors, 47 warnings, 84 sections, 411664 bytes` (exit 0)
- 84 sections, 411664 bytes

## Live checks (14)

- root 'E19-D03 / 06 cmp-183-periods' at (0, 5600): read back the name exactly after the first section call; size 3280 x 3416
- after touchTexts + relayout: the annotation column (estimated 1385 px) ends inside the root (h 3416); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'CMP-183 · VolumeProfilePane — ref frame (Session)': read back 360 x 560 at (80, 80); clip on, no child spills
- frame 'CMP-183 · VolumeProfilePane — ref frame (Fixed range)': read back 360 x 560 at (520, 80); clip on, no child spills
- frame 'CMP-183 · VolumeProfilePane — ref frame (Visible range)': read back 360 x 560 at (960, 80); clip on, no child spills
- frame 'CMP-183 · VolumeProfilePane — ref frame (Anchored)': read back 360 x 560 at (1400, 80); clip on, no child spills
- frame 'CMP-183 · VolumeProfilePane — ref frame (Composite)': read back 360 x 560 at (1840, 80); clip on, no child spills
- frame 'SCR-038∕developing-dark': read back 1280 x 800 at (80, 720); clip on, no child spills
- frame 'SCR-038∕final-dark': read back 1280 x 800 at (1440, 720); clip on, no child spills
- frame 'SCR-038∕approximated-dark': read back 1280 x 800 at (80, 1600); clip on, no child spills
- frame 'SCR-038∕partial-dark': read back 1280 x 800 at (1440, 1600); clip on, no child spills
- frame 'SCR-038∕edge-5000-rows-dark': read back 1280 x 800 at (80, 2480); clip on, no child spills
- local tokens: create the sets of local-tokens.json ('E19-D03 local · dark', '· light', '· hc', each active only in its theme) before the first section call; color.tpo.letter and color.tpo.initialbalance bind them
- export docs/design/E19/img/E19-D03-06-cmp-183-periods.png; record the board id and the PNG size

## Readings (2)

- R-K3: the bracket's developing edge (no end cap, §7.2) is the value-area edge on the last price's side
- R-K6: where rows are under 12 px, a node glyph (▶ / ◀) whose 10 px line would touch the previous one of its kind is not drawn; the row keeps its bar and the mirror and the table carry the word

## Derivations (6)

- "CMP-183 · VolumeProfilePane — ref frame (Session)": the example "CMP-183 · VolumeProfilePane — ref frame (<word>)" (spec L263) with this frame's values
- "CMP-183 · VolumeProfilePane — ref frame (Fixed range)": the example "CMP-183 · VolumeProfilePane — ref frame (<word>)" (spec L263) with this frame's values
- "CMP-183 · VolumeProfilePane — ref frame (Visible range)": the example "CMP-183 · VolumeProfilePane — ref frame (<word>)" (spec L263) with this frame's values
- "CMP-183 · VolumeProfilePane — ref frame (Anchored)": the example "CMP-183 · VolumeProfilePane — ref frame (<word>)" (spec L263) with this frame's values
- "CMP-183 · VolumeProfilePane — ref frame (Composite)": the example "CMP-183 · VolumeProfilePane — ref frame (<word>)" (spec L263) with this frame's values
- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 438 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (37)

- W-10: "Developing · as of {HH:MM} UTC" (spec L391) filled from the world
- "Session" (spec L263)
- "One per session, side by side" (spec L263)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "POC" (spec L5)
- "VAH" (spec L120)
- "VAL" (spec L120)
- "Fixed range" (spec L263)
- "Visible range" (spec L263)
- "Anchored" (spec L263)
- "contract pending A-1" (spec L263)
- W-11: "Final" (spec L392)
- "Composite" (spec L263)
- D02 W-21: "Covered: {from} – {to} · {n} of {m} sessions" (D02 L370) filled from the world
- W-12: "Rows merged: {k} levels per row" (spec L393) filled from the world
- D02 W-2: "Aligned to {symbol} · {interval}" (D02 L351) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "Period" (spec L261)
- "Input" (spec L9)
- "Volume" (spec L5)
- "VA%" (D02 L135)
- "Row" (spec L253)
- "VWAP" (spec L61)
- D02 W-29: "Histogram" (D02 L378)
- D02 W-29: "Table" (D02 L378)
- "Presets" (D02 L113)
- "Settings" (D02 L100)
- "HVN" (spec L124)
- "LVN" (spec L124)
- "Single prints" (spec L200)
- W-2: "{k} hidden" (spec L383) filled from the world
- W-6: "Show tested" (spec L387)
- "BTCUSDT" (spec L62)
- W-14: "(estimated)" (spec L395)
- D02 W-9: "Delta not available before {HH:MM} UTC" (D02 L358) filled from the world
- D02 W-6: "Partial: {n} of {m} requested days recorded" (D02 L355) filled from the world
- D02 W-7: "Gaps excluded: {k} ranges, {duration}" (D02 L356) filled from the world

## Copy gaps (3)

- "30m": the bound chart's interval word (kit world: 30-minute bars), filling D02 W-2's {interval}
- CMP-227 drawn as a bordered pill with a 12 × 8 hatched key and its word; its shipped tokens are `15` CMP-227's (§7.3), bound live by the component
- "50 h": D02 W-7's {duration} in whole hours (kit form)

## Fallbacks (5)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit stand-in: the engine bakes the HVN / LVN triangles (6 × 6 px) into the bar instance (§3 rows 5, 6); the board draws them as the characters ▶ / ◀ in type.num.xs (no triangle shape in the node set)
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen or a measurement, never product UI
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the chart beside the panel is a plain SCR-030 price pane (candles, grid, price axis) for alignment only
- kit stand-in: pattern.hatch.estimated (45°, 2 px pitch, 30 % over the fill, D05E11:313) is a registered pattern id, not a token; the board draws 1 px color.surface.canvas 'hatch line · ' strokes at an 8 px pitch over each approximated bar (rotated 45° by the post-step), clipped to the bar

## Sources (4)

- spec E19-D03.md md5 928db4e4 and hand-off md5 fb2077ba (§0 L79; RULED comment 6580374205)
- D02 E19-D02.md md5 1299df3b at bed73afaa (read via git show bed73afaa; re-pinned when PR #5487 merges)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.tpo.*, PROPOSED, §2.1)

## Tokens (37)

- type.ui.label
- color.text.primary
- type.ui.caption
- color.text.secondary
- size.icon.sm
- space.inset.sm
- space.inset.xs
- radius.control
- color.action.secondary.default
- color.border.default
- border.hairline
- space.stack.xs
- color.surface.raised
- color.profile.bar
- color.profile.valuearea
- color.profile.poc
- type.num.xs
- color.surface.canvas
- color.surface.app
- color.border.strong
- radius.card
- type.num.sm
- color.surface.sunken
- color.surface.selected
- color.tpo.letter
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.up
- color.candle.down
- radius.badge
- color.status.info.strong
- color.status.info.subtle
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
- space.inset.lg
