# E19-D03 / 05 greyscale-cvd

File `E19-D03 boards`, page `E19-D03`; export `docs/design/E19/img/E19-D03-05-greyscale-cvd.png`; sheet `05-greyscale-cvd.json` (validated); theme light.

Board 05 of ten (§0 L78: SCR-038/greyscale-dark, SCR-038/greyscale-light (delta input), SCR-038/cvd-sheet). Grid (30400, 0); 3280 x 1896 px; "page E19-D03 · board 05 · r1".

## Frames

- `SCR-038∕greyscale-dark` (dark, 1280 x 800)
- `SCR-038∕greyscale-light` (light, 1280 x 800)
- `SCR-038∕cvd-sheet` (light, 1280 x 800)

## Validator and size

- `05-greyscale-cvd.json: 0 errors, 17 warnings, 23 sections, 84216 bytes` (exit 0)
- 23 sections, 84216 bytes

## Live checks (11)

- greyscale: crop 'SCR-038/greyscale-dark' from the board export and run the CVD simulation's greyscale (Rec. 601) on it; attach the PNG beside the board's
- greyscale: crop 'SCR-038/greyscale-light' from the board export and run the CVD simulation's greyscale (Rec. 601) on it; attach the PNG beside the board's
- root 'E19-D03 / 05 greyscale-cvd' at (30400, 0): read back the name exactly after the first section call; size 3280 x 1896
- after touchTexts + relayout: the annotation column (estimated 844 px) ends inside the root (h 1896); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-038∕greyscale-dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-038∕greyscale-light': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-038∕cvd-sheet': read back 1280 x 800 at (80, 960); clip on, no child spills
- local tokens: create the sets of local-tokens.json ('E19-D03 local · dark', '· light', '· hc', each active only in its theme) before the first section call; color.tpo.letter and color.tpo.initialbalance bind them
- theme: activate the light token set (and 'E19-D03 local · light') before exporting board 05; read back one bound fill (color.surface.raised) as the light value
- export docs/design/E19/img/E19-D03-05-greyscale-cvd.png; record the board id and the PNG size
- kit reading R-K1: export board 05 a second time under the dark set as docs/design/E19/img/E19-D03-05-greyscale-cvd-dark.png; its '-dark' frames are read from that export, its '-light' frames from docs/design/E19/img/E19-D03-05-greyscale-cvd.png

## Readings (2)

- R-K2: a greyscale frame is drawn token-bound, identical to its colour frame; the greyscale is the export's Rec. 601 luma transform (CVD:39, the repo's CVD simulation) applied to the frame's crop of the board PNG (Penpot binds tokens, not a filter); the transform's PNG is the frame's review image
- R-K3: the bracket's developing edge (no end cap, §7.2) is the value-area edge on the last price's side

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 438 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (32)

- D02 W-2: "Aligned to {symbol} · {interval}" (D02 L351) filled from the world
- W-10: "Developing · as of {HH:MM} UTC" (spec L391) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "Period" (spec L261)
- "Session" (spec L263)
- "Input" (spec L9)
- "Volume" (spec L5)
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
- "Delta" (spec L217)
- "deuteranopia" (spec L95)
- "protanopia" (spec L95)
- "tritanopia" (spec L95)
- "SCR-038/cvd-sheet" (spec L78)
- §2.3 L160: the ratios table, cells verbatim (normal / greyscale / deuteranopia / protanopia / tritanopia)
- "normal / greyscale / deuteranopia / protanopia / tritanopia" (spec L158)
- §2.3 L158: the lead and the buy / sell sentence, verbatim (code spans unformatted)

## Copy gaps (1)

- "30m": the bound chart's interval word (kit world: 30-minute bars), filling D02 W-2's {interval}

## Fallbacks (3)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the chart beside the panel is a plain SCR-030 price pane (candles, grid, price axis) for alignment only
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen or a measurement, never product UI

## Sources (4)

- spec E19-D03.md md5 928db4e4 and hand-off md5 fb2077ba (§0 L78; RULED comment 6580374205)
- D02 E19-D02.md md5 1299df3b at bed73afaa (read via git show bed73afaa; re-pinned when PR #5487 merges)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.tpo.*, PROPOSED, §2.1)

## Tokens (38)

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
- color.profile.bar
- color.profile.poc
- color.surface.app
- color.sell.default
- color.buy.default
- color.text.tertiary
- color.border.strong
- radius.card
- type.ui.heading-sm
- space.inset.lg
- space.stack.md
- space.inset.xl
- space.stack.sm
