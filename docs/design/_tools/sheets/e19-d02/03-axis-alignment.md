# E19-D02 / 03 axis-alignment

File `E19-D02 boards`, page `E19-D02`; export `docs/design/E19/img/E19-D02-03-axis-alignment.png`; sheet `03-axis-alignment.json` (validated); theme dark.

Board 03 of 10 (§0 L74: SCR-038/aligned-linear, SCR-038/aligned-log, SCR-038/aligned-mid-fit, SCR-038/not-aligned). Grid (8000, 0); 3280 x 1878 px; "page E19-D02 · board 03 · r1".

## Frames

- `SCR-038∕aligned-linear` (1280 x 800)
- `SCR-038∕aligned-log` (1280 x 800)
- `SCR-038∕aligned-mid-fit` (1280 x 800)
- `SCR-038∕not-aligned` (1280 x 800)

## Validator and size

- `03-axis-alignment.json: 0 errors, 41 warnings, 49 sections, 220215 bytes` (exit 0)
- 49 sections, 220215 bytes

## Live checks (22)

- frame 'SCR-038∕aligned-linear': 'board marker · boundary 644500' anchored top-left at (896, 468) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-linear': 'board marker · boundary 644600' anchored top-left at (896, 458) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-linear': 'board marker · boundary 644700' anchored top-left at (896, 447) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-linear': 'board marker · boundary 644800' anchored top-left at (896, 437) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-linear': 'board marker · row boundaries' anchored top-left at (24, 92) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-log': 'board marker · boundary 666000' anchored top-left at (896, 216) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-log': 'board marker · boundary 664000' anchored top-left at (896, 233) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-log': 'board marker · boundary 614000' anchored top-left at (896, 671) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-log': 'board marker · boundary 612000' anchored top-left at (896, 689) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-log': 'board marker · log heights' anchored top-left at (24, 92) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-mid-fit': 'board marker · auto-fit frame 1' anchored top-left at (12, 76) in 'auto-fit frame 1'; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-mid-fit': 'board marker · auto-fit frame 2' anchored top-left at (12, 76) in 'auto-fit frame 2'; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕aligned-mid-fit': 'board marker · frame divider' anchored top-left at (639, 0) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕not-aligned': 'board marker · announced once, polite' anchored top-left at (24, 92) in the frame; keep that anchor after relayout: do not centre it
- root 'E19-D02 / 03 axis-alignment' at (8000, 0): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 1085 px) ends inside the root (h 1878); raise the root's h to max(annotation end, footer end) + 80 if not
- centring: no block on this board is re-centred by default; only a block a check in this list names 'centred horizontally and vertically' is centred (on the axes it names); every other block keeps the anchor and x, y given here (frames top-left on the grid, the annotation column top-left right of the frames, board markers top-left in their frame)
- frame 'SCR-038∕aligned-linear': read back 1280 x 800 at (80, 80) (top-left anchor); clip on, no child spills
- frame 'SCR-038∕aligned-log': read back 1280 x 800 at (1440, 80) (top-left anchor); clip on, no child spills
- frame 'SCR-038∕aligned-mid-fit': read back 1280 x 800 at (80, 960) (top-left anchor); clip on, no child spills
- frame 'SCR-038∕not-aligned': read back 1280 x 800 at (1440, 960) (top-left anchor); clip on, no child spills
- theme: the dark token set is active (greyscale wire); export docs/design/E19/img/E19-D02-03-axis-alignment.png; record the board id and the PNG size

## Readings (1)

- developing bracket: the open end is the value-area edge on the last price's side (PD-1 leaves the side unworded)

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 416 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Not drawn (0)

## Copy keys (28)

- W-2: "Aligned to {symbol} · {interval}" (spec L351) filled from the world
- W-1: "Profile: BTCUSDT" (spec L350)
- W-5: "Final" (spec L354)
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
- "POC" (spec L63)
- "VAH" (spec L98)
- "VAL" (spec L98)
- "VA" (spec L47)
- "Composite" (spec L53)
- "log" (spec L1)
- W-4: "Developing · as of {HH:MM} UTC" (spec L353) filled from the world
- W-3: "Own price scale — not aligned" (spec L352)
- "percent" (spec L174)

## Copy gaps (9)

- "30m": the bound chart's interval word (the world's 30-minute bars, or n of them as one candle), drawn in the chart header and filling W-2's {interval}
- "Row boundaries (this frame)": board marker title (kit)
- "4h": the bound chart's interval word (the world's 30-minute bars, or n of them as one candle), drawn in the chart header and filling W-2's {interval}
- "Log row heights (this frame)": board marker title (kit)
- date form "10 Oct" (day, month) for W-21's {from} / {to} and W-6's days: §12 gives no format
- "Auto-fit frame 1 of 2": board marker title (kit)
- "Auto-fit frame 2 of 2": board marker title (kit)
- "announced once, polite": board marker title (kit): the R-4 announcement
- "announced once, polite": the kit's marker title for a string a screen reader hears (board marker)

## Fallbacks (6)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- wire stand-in: the HVN / LVN glyphs are the characters '>' / '<' of the §3.1 sketch's legend in type.num.sm; their shapes are E19-D03's (PD-3)
- kit choice: the chart beside the panel is a plain SCR-030 price pane (grey candles, grid, price axis, time axis) for alignment only; candle direction is not encoded (greyscale wire, §2)
- kit choice: the terminal's TopBar and StatusBar are wordless placeholders (E10's chrome, not this spec's); the app's global chrome band is the only environment carrier (R-1) and no frame draws one
- kit choice: a board marker box ('board marker · …', 1 px color.border.default outline on color.surface.canvas) names a measurement, a gesture or an order, never product UI
- kit choice: a string a screen reader hears (an accessible name, a description, a polite announcement) is drawn for the board as caption text in a bordered 'board marker' box (not on screen in the product)

## Icons (3)

- chevron-down: this kit's local-icons.js (not in the repo's run/local-icons.js)
- arrow-down: the repo's run/local-icons.js
- arrow-up: the repo's run/local-icons.js

## Sources (3)

- spec E19-D02.md md5 40b8a21b (the boards PR's text: §0 drawn, §18 As built; read via checkout; §0 L74; BQ list RULED, comment 6576655478)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: the shared token-sync.json (no local rows); wire tokens only (§2)

## Tokens (18)

- type.ui.label
- color.text.primary
- type.ui.caption
- color.text.secondary
- space.inset.sm
- size.icon.sm
- space.inset.xs
- radius.control
- color.surface.raised
- color.border.default
- border.hairline
- type.num.sm
- color.surface.canvas
- space.stack.xs
- color.text.tertiary
- radius.card
- space.stack.sm
- space.inset.lg
