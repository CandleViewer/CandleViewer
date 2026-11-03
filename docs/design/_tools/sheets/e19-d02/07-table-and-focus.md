# E19-D02 / 07 table-and-focus

File `E19-D02 boards`, page `E19-D02`; export `docs/design/E19/img/E19-D02-07-table-and-focus.png`; sheet `07-table-and-focus.json` (validated); theme dark.

Board 07 of 10 (§0 L78: SCR-038/table). Grid (4000, 3200); 1920 x 1011 px; "page E19-D02 · board 07 · r1".

## Frames

- `SCR-038∕table` (1280 x 800)

## Validator and size

- `07-table-and-focus.json: 0 errors, 9 warnings, 26 sections, 64806 bytes` (exit 0)
- 26 sections, 64806 bytes

## Live checks (8)

- frame 'SCR-038∕table': 'board marker · focus order' anchored top-left at (600, 84) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕table': 'board marker · MEMO A-6 columns' anchored top-left at (600, 218) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕table': 'board marker · announced on the swap' anchored top-left at (600, 318) in the frame; keep that anchor after relayout: do not centre it
- root 'E19-D02 / 07 table-and-focus' at (4000, 3200): read back the name exactly after the first section call; size 1920 x 1011
- after touchTexts + relayout: the annotation column (estimated 566 px) ends inside the root (h 1011); raise the root's h to max(annotation end, footer end) + 80 if not
- centring: no block on this board is re-centred by default; only a block a check in this list names 'centred horizontally and vertically' is centred (on the axes it names); every other block keeps the anchor and x, y given here (frames top-left on the grid, the annotation column top-left right of the frames, board markers top-left in their frame)
- frame 'SCR-038∕table': read back 1280 x 800 at (80, 80) (top-left anchor); clip on, no child spills
- theme: the dark token set is active (greyscale wire); export docs/design/E19/img/E19-D02-07-table-and-focus.png; record the board id and the PNG size

## Readings (1)

- developing bracket: the open end is the value-area edge on the last price's side (PD-1 leaves the side unworded)

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 416 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Not drawn (2)

- W-34 "{level word} {price}: volume {v}, delta {d}, in value area" / "… outside value area" (spec L383): not drawn: announcement-only (Enter on a histogram-mirror row reads it, §11 L340; the mirror is absent in Table view) — the text is binding
- W-33 "POC {price}, VAH {price}, VAL {price}" (spec L382): not drawn: announcement-only (the panel's polite region, latest value only, at most once per 2 s: §11 L344, R-4); the annotation's 'Levels (derived)' line carries the values it would announce — the text is binding

## Copy keys (35)

- "Price" (spec L339)
- "Volume" (spec L33)
- "Delta" (spec L54)
- "% of POC" (spec L339)
- "Value area" (spec L145)
- "Outside VA" (spec L339)
- W-2: "Aligned to {symbol} · {interval}" (spec L351) filled from the world
- W-1: "Profile: BTCUSDT" (spec L350)
- W-4: "Developing · as of {HH:MM} UTC" (spec L353) filled from the world
- "Period" (spec L135)
- "Session" (spec L53)
- "Input" (spec L9)
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
- "In VA" (spec L339)
- "load more rows" (spec L339)
- "header controls → histogram mirror → legend → table" (spec L340)
- "TPO count" (spec L339)
- "Node" (spec L339)
- "Naked POC" (spec L238)
- "Single print" (spec L145)
- "Developing / Final" (spec L239)
- "Estimated" (spec L339)
- W-35: "Showing table" (spec L384)
- W-35: "Showing histogram" (spec L384)

## Copy gaps (4)

- "30m": the bound chart's interval word (the world's 30-minute bars, or n of them as one candle), drawn in the chart header and filling W-2's {interval}
- "Focus order": board marker title (kit)
- "Further columns": board marker title (kit)
- "announced on the swap": the kit's marker title for a string a screen reader hears (board marker)

## Fallbacks (7)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- wire stand-in: a focused control or row carries a 2 px color.text.primary outline (the system outline, §11 R2); the focus-ring token is hi-fi (E19-D03)
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

- spec E19-D02.md md5 40b8a21b (the boards PR's text: §0 drawn, §18 As built; read via checkout; §0 L78; BQ list RULED, comment 6576655478)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: the shared token-sync.json (no local rows); wire tokens only (§2)

## Tokens (19)

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
- border.thick
- space.stack.xs
- color.text.tertiary
- radius.card
- space.stack.sm
- space.inset.lg
