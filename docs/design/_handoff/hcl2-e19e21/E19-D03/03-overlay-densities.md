# E19-D03 / 03 overlay-densities

File `E19-D03 boards`, page `E19-D03`; export `docs/design/E19/img/E19-D03-03-overlay-densities.png`; sheet `03-overlay-densities.json` (validated); theme dark.

Board 03 of ten (§0 L76: SCR-038/overlay-compact-dark, SCR-038/overlay-dense-dark, SCR-038/overlay-comfortable-dark, SCR-038/not-aligned-dark). Grid (15200, 0); 3280 x 1896 px; "page E19-D03 · board 03 · r1".

## Frames

- `SCR-038∕overlay-compact-dark` (dark, 1280 x 800)
- `SCR-038∕overlay-dense-dark` (dark, 1280 x 800)
- `SCR-038∕overlay-comfortable-dark` (dark, 1280 x 800)
- `SCR-038∕not-aligned-dark` (dark, 1280 x 800)

## Validator and size

- `03-overlay-densities.json: 0 errors, 15 warnings, 30 sections, 163084 bytes` (exit 0)
- 30 sections, 163084 bytes

## Live checks (8)

- root 'E19-D03 / 03 overlay-densities' at (15200, 0): read back the name exactly after the first section call; size 3280 x 1896
- after touchTexts + relayout: the annotation column (estimated 914 px) ends inside the root (h 1896); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-038∕overlay-compact-dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-038∕overlay-dense-dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-038∕overlay-comfortable-dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-038∕not-aligned-dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- local tokens: create the sets of local-tokens.json ('E19-D03 local · dark', '· light', '· hc', each active only in its theme) before the first section call; color.tpo.letter and color.tpo.initialbalance bind them
- export docs/design/E19/img/E19-D03-03-overlay-densities.png; record the board id and the PNG size

## Readings (2)

- overlay bars: 30 % of the pane's plot width (365 px of 1216, §10.2 PROPOSED), from the pane's right edge toward the left; the price axis and its last-price label stay uncovered
- R-K3: the bracket's developing edge (no end cap, §7.2) is the value-area edge on the last price's side

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 438 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (28)

- D02 §3.2: "Profile · Visible range ▾ · Volume ▾ · Histogram │ Table · ⚙" (D02 L159)
- "Profile" (spec L5)
- "Visible range" (spec L263)
- "Volume" (spec L5)
- D02 W-29: "Histogram" (D02 L378)
- D02 W-29: "Table" (D02 L378)
- "⚙" (D02 L159)
- W-2: "{k} hidden" (spec L383) filled from the world
- W-6: "Show tested" (spec L387)
- "BTCUSDT" (spec L62)
- "POC" (spec L5)
- "VAH" (spec L120)
- "VAL" (spec L120)
- D02 W-3: "Own price scale — not aligned" (D02 L352)
- W-10: "Developing · as of {HH:MM} UTC" (spec L391) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "Period" (spec L261)
- "Session" (spec L263)
- "Input" (spec L9)
- "VA%" (D02 L135)
- "Row" (spec L253)
- "VWAP" (spec L61)
- "Presets" (D02 L113)
- "Settings" (D02 L100)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "HVN" (spec L124)
- "LVN" (spec L124)
- "Single prints" (spec L200)

## Copy gaps (1)

- "30m": the bound chart's interval word (kit world: 30-minute bars), filling D02 W-2's {interval}

## Fallbacks (2)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the chart beside the panel is a plain SCR-030 price pane (candles, grid, price axis) for alignment only

## Sources (4)

- spec E19-D03.md md5 928db4e4 and hand-off md5 fb2077ba (§0 L76; RULED comment 6580374205)
- D02 E19-D02.md md5 1299df3b at bed73afaa (read via git show bed73afaa; re-pinned when PR #5487 merges)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.tpo.*, PROPOSED, §2.1)

## Tokens (34)

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
- color.surface.selected
- size.icon
- color.surface.canvas
- color.grid.line
- type.num.sm
- color.axis.text
- color.candle.wick
- color.candle.down
- color.candle.up
- color.profile.bar
- color.profile.valuearea
- color.profile.poc
- type.num.xs
- color.surface.raised
- color.surface.app
- space.inset.md
- color.surface.sunken
- space.stack.xs
- color.tpo.letter
- color.text.tertiary
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
