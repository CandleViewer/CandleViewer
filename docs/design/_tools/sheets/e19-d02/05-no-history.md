# E19-D02 / 05 no-history

File `E19-D02 boards`, page `E19-D02`; export `docs/design/E19/img/E19-D02-05-no-history.png`; sheet `05-no-history.json` (validated); theme dark.

Board 05 of 10 (§0 L76: SCR-038/no-history-owner, SCR-038/no-history-sentence, SCR-038/no-history-view-as). Grid (16000, 0); 3280 x 1878 px; "page E19-D02 · board 05 · r1".

## Frames

- `SCR-038∕no-history-owner` (1280 x 800)
- `SCR-038∕no-history-sentence` (1280 x 800)
- `SCR-038∕no-history-view-as` (1280 x 800)

## Validator and size

- `05-no-history.json: 0 errors, 25 warnings, 18 sections, 74980 bytes` (exit 0)
- 18 sections, 74980 bytes

## Live checks (7)

- root 'E19-D02 / 05 no-history' at (16000, 0): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 789 px) ends inside the root (h 1878); raise the root's h to max(annotation end, footer end) + 80 if not
- centring: no block on this board is re-centred by default; only a block a check in this list names 'centred horizontally and vertically' is centred (on the axes it names); every other block keeps the anchor and x, y given here (frames top-left on the grid, the annotation column top-left right of the frames, board markers top-left in their frame)
- frame 'SCR-038∕no-history-owner': read back 1280 x 800 at (80, 80) (top-left anchor); clip on, no child spills
- frame 'SCR-038∕no-history-sentence': read back 1280 x 800 at (1440, 80) (top-left anchor); clip on, no child spills
- frame 'SCR-038∕no-history-view-as': read back 1280 x 800 at (80, 960) (top-left anchor); clip on, no child spills
- theme: the dark token set is active (greyscale wire); export docs/design/E19/img/E19-D02-05-no-history.png; record the board id and the PNG size

## Readings (1)

- board 05 condition: the window has no recorded history and BTCUSDT was never recorded (a synthetic condition for this board's three frames, so W-11 holds; the bound chart still shows public bars); the three variants share it so they compare

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 416 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Not drawn (0)

## Copy keys (24)

- W-11: "History starts when you record {symbol} — recording has not begun yet." (spec L360) filled from the world
- W-12: "Nothing is missing or broken: CandleViewer keeps only what it records." (spec L361)
- W-13: "Record this symbol" (spec L362)
- W-10: "History starts {ts} — recording began then." (spec L359) filled from the world
- W-2: "Aligned to {symbol} · {interval}" (spec L351) filled from the world
- W-1: "Profile: BTCUSDT" (spec L350)
- "Period" (spec L135)
- "Session" (spec L53)
- "Input" (spec L9)
- "Volume" (spec L33)
- "VA%" (spec L135)
- "Row" (spec L47)
- "VWAP" (spec L54)
- W-29: "Histogram" (spec L378)
- W-29: "Table" (spec L378)
- "Presets" (spec L113)
- "Settings" (spec L100)
- W-19: "Row size: {n} ticks ({price})" (spec L368) filled from the world
- "HVN" (spec L145)
- "LVN" (spec L142)
- "Single prints" (spec L145)
- "BTCUSDT" (spec L68)
- W-14: "Only the owner can change recording." (spec L363)
- W-15: "Read-only while viewing as {user}." (spec L364) filled from the world

## Copy gaps (2)

- "30m": the bound chart's interval word (the world's 30-minute bars, or n of them as one candle), drawn in the chart header and filling W-2's {interval}
- "Sam": W-15's {user}, a synthetic display name (no account identifier, R-1)

## Fallbacks (4)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- wire stand-in: the HVN / LVN glyphs are the characters '>' / '<' of the §3.1 sketch's legend in type.num.sm; their shapes are E19-D03's (PD-3)
- kit choice: the chart beside the panel is a plain SCR-030 price pane (grey candles, grid, price axis, time axis) for alignment only; candle direction is not encoded (greyscale wire, §2)
- kit choice: the terminal's TopBar and StatusBar are wordless placeholders (E10's chrome, not this spec's); the app's global chrome band is the only environment carrier (R-1) and no frame draws one

## Icons (3)

- chevron-down: this kit's local-icons.js (not in the repo's run/local-icons.js)
- arrow-down: the repo's run/local-icons.js
- arrow-up: the repo's run/local-icons.js

## Sources (3)

- spec E19-D02.md md5 40b8a21b (the boards PR's text: §0 drawn, §18 As built; read via checkout; §0 L76; BQ list RULED, comment 6576655478)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: the shared token-sync.json (no local rows); wire tokens only (§2)

## Tokens (18)

- type.ui.caption
- color.text.primary
- space.inset.md
- radius.control
- color.surface.raised
- border.hairline
- type.ui.label
- space.inset.sm
- color.text.secondary
- size.icon.sm
- space.inset.xs
- color.border.default
- type.num.sm
- color.surface.canvas
- space.stack.xs
- color.text.tertiary
- space.stack.sm
- space.inset.lg
