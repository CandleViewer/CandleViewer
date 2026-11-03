# E19-D03 / 02 docked-light

File `E19-D03 boards`, page `E19-D03`; export `docs/design/E19/img/E19-D03-02-docked-light.png`; sheet `02-docked-light.json` (validated); theme light.

Board 02 of ten (§0 L75: SCR-038/docked-compact-light (delta input: the zero-delta tick in light)). Grid (7600, 0); 1920 x 1016 px; "page E19-D03 · board 02 · r1".

## Frames

- `SCR-038∕docked-compact-light` (light, 1280 x 800)

## Validator and size

- `02-docked-light.json: 0 errors, 8 warnings, 9 sections, 37067 bytes` (exit 0)
- 9 sections, 37067 bytes

## Live checks (6)

- root 'E19-D03 / 02 docked-light' at (7600, 0): read back the name exactly after the first section call; size 1920 x 1016
- after touchTexts + relayout: the annotation column (estimated 551 px) ends inside the root (h 1016); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-038∕docked-compact-light': read back 1280 x 800 at (80, 80); clip on, no child spills
- local tokens: create the sets of local-tokens.json ('E19-D03 local · dark', '· light', '· hc', each active only in its theme) before the first section call; color.tpo.letter and color.tpo.initialbalance bind them
- theme: activate the light token set (and 'E19-D03 local · light') before exporting board 02; read back one bound fill (color.surface.raised) as the light value
- export docs/design/E19/img/E19-D03-02-docked-light.png; record the board id and the PNG size

## Readings (1)

- R-K3: the bracket's developing edge (no end cap, §7.2) is the value-area edge on the last price's side

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 438 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (24)

- D02 W-2: "Aligned to {symbol} · {interval}" (D02 L351) filled from the world
- W-10: "Developing · as of {HH:MM} UTC" (spec L391) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "Period" (spec L261)
- "Session" (spec L263)
- "Input" (spec L9)
- "Delta" (spec L217)
- "VA%" (D02 L135)
- "Row" (spec L253)
- "VWAP" (spec L61)
- D02 W-29: "Histogram" (D02 L378)
- D02 W-29: "Table" (D02 L378)
- "Presets" (D02 L113)
- "Settings" (D02 L100)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "HVN" (spec L124)
- "LVN" (spec L124)
- "Single prints" (spec L200)
- W-2: "{k} hidden" (spec L383) filled from the world
- W-6: "Show tested" (spec L387)
- "BTCUSDT" (spec L62)
- "POC" (spec L5)
- "VAH" (spec L120)
- "VAL" (spec L120)

## Copy gaps (1)

- "30m": the bound chart's interval word (kit world: 30-minute bars), filling D02 W-2's {interval}

## Fallbacks (2)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the chart beside the panel is a plain SCR-030 price pane (candles, grid, price axis) for alignment only

## Sources (4)

- spec E19-D03.md md5 928db4e4 and hand-off md5 fb2077ba (§0 L75; RULED comment 6580374205)
- D02 E19-D02.md md5 1299df3b at bed73afaa (read via git show bed73afaa; re-pinned when PR #5487 merges)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.tpo.*, PROPOSED, §2.1)

## Tokens (33)

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
- type.num.sm
- color.surface.sunken
- color.surface.selected
- space.stack.xs
- color.surface.raised
- color.profile.valuearea
- color.surface.canvas
- type.num.xs
- color.tpo.letter
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.up
- color.candle.down
- color.sell.default
- color.buy.default
- color.text.tertiary
- color.profile.poc
- color.surface.app
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
