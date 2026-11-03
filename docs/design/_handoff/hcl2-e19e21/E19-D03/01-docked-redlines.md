# E19-D03 / 01 docked-redlines

File `E19-D03 boards`, page `E19-D03`; export `docs/design/E19/img/E19-D03-01-docked-redlines.png`; sheet `01-docked-redlines.json` (validated); theme dark.

Board 01 of ten (§0 L74: SCR-038/docked-compact-dark, SCR-038/docked-dense-dark, SCR-038/docked-comfortable-dark; insets SCR-038/degraded-dark, SCR-038/text-scale-200-dark). Grid (0, 0); 3280 x 1896 px; "page E19-D03 · board 01 · r1".

## Frames

- `SCR-038∕docked-compact-dark` (dark, 1280 x 800)
- `SCR-038∕docked-dense-dark` (dark, 1280 x 800)
- `SCR-038∕docked-comfortable-dark` (dark, 1280 x 800)
- `SCR-038∕degraded-dark` (dark, 280 x 728)
- `SCR-038∕text-scale-200-dark` (dark, 280 x 728)

## Validator and size

- `01-docked-redlines.json: 0 errors, 42 warnings, 36 sections, 139410 bytes` (exit 0)
- 36 sections, 139410 bytes

## Live checks (10)

- text-scale inset: after relayout, the header and legend hold every wrapped row; raise their h if not
- root 'E19-D03 / 01 docked-redlines' at (0, 0): read back the name exactly after the first section call; size 3280 x 1896
- after touchTexts + relayout: the annotation column (estimated 914 px) ends inside the root (h 1896); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-038∕docked-compact-dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-038∕docked-dense-dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-038∕docked-comfortable-dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-038∕degraded-dark': read back 280 x 728 at (1440, 960); clip on, no child spills
- frame 'SCR-038∕text-scale-200-dark': read back 280 x 728 at (1800, 960); clip on, no child spills
- local tokens: create the sets of local-tokens.json ('E19-D03 local · dark', '· light', '· hc', each active only in its theme) before the first section call; color.tpo.letter and color.tpo.initialbalance bind them
- export docs/design/E19/img/E19-D03-01-docked-redlines.png; record the board id and the PNG size

## Readings (3)

- R-K3: the bracket's developing edge (no end cap, §7.2) is the value-area edge on the last price's side
- board 01 redlines: §10.1 L289 values drawn as a board marker over the chart area
- R-K4: text scale ×2.0 is drawn with the nearest type tokens (caption / label -> type.ui.heading-lg 20 px; type.num.xs -> type.num.xl 20 px; type.num.sm -> type.num.lg 16 px); at ×2.0 a level label keeps its word and drops its price (the 56 px gutter holds 4 characters of 12 px advance; §2.5's word-hide threshold uses the scaled size); the price stays in the mirror, the Levels group and the table

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 438 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (25)

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
- D02 W-16: "1 s refresh" (D02 L365)

## Copy gaps (2)

- "30m": the bound chart's interval word (kit world: 30-minute bars), filling D02 W-2's {interval}
- E17's corner tag (D02E17:221, reused unchanged) drawn as a neutral chip with the local 'refresh' glyph in the status slot; its tokens are E17's

## Fallbacks (4)

- kit choice: redline callouts are caption text joined to the specimen by a 1 px color.border.strong leader (board markers, not product UI)
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen or a measurement, never product UI
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the chart beside the panel is a plain SCR-030 price pane (candles, grid, price axis) for alignment only

## Sources (4)

- spec E19-D03.md md5 928db4e4 and hand-off md5 fb2077ba (§0 L74; RULED comment 6580374205)
- D02 E19-D02.md md5 1299df3b at bed73afaa (read via git show bed73afaa; re-pinned when PR #5487 merges)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.tpo.*, PROPOSED, §2.1)

## Tokens (36)

- type.ui.label
- color.text.primary
- type.ui.caption
- color.text.secondary
- space.stack.xs
- space.inset.sm
- color.surface.canvas
- color.border.strong
- border.hairline
- radius.card
- size.icon.sm
- space.inset.xs
- radius.control
- color.action.secondary.default
- color.border.default
- type.num.sm
- color.surface.sunken
- color.surface.selected
- color.surface.raised
- color.profile.valuearea
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
- space.inset.md
- radius.badge
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
- space.inset.lg
