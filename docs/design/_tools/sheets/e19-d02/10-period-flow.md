# E19-D02 / 10 period-flow

File `E19-D02 boards`, page `E19-D02`; export `docs/design/E19/img/E19-D02-10-period-flow.png`; sheet `10-period-flow.json` (validated); theme dark.

Board 10 of 10 (§0 L81: SCR-038/period-menu, SCR-038/fixed-range-drag, SCR-038/anchored-place). Grid (16000, 3200); 3280 x 1878 px; "page E19-D02 · board 10 · r1".

## Frames

- `SCR-038∕period-menu` (1280 x 800)
- `SCR-038∕fixed-range-drag` (1280 x 800)
- `SCR-038∕anchored-place` (1280 x 800)

## Validator and size

- `10-period-flow.json: 0 errors, 28 warnings, 26 sections, 119349 bytes` (exit 0)
- 26 sections, 119349 bytes

## Live checks (14)

- frame 'SCR-038∕period-menu': 'board marker · kinds' anchored top-left at (620, 84) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕period-menu': 'board marker · event profile.period_changed' anchored top-left at (620, 213) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕period-menu': 'board marker · event profile.mode_changed' anchored top-left at (620, 286) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕period-menu': 'board marker · event profile.va_percent_changed' anchored top-left at (620, 359) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕fixed-range-drag': 'board marker · Shift-drag range' anchored top-left at (378, 32) in 'SCR-030 price pane'; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕anchored-place': 'board marker · anchor' anchored top-left at (225, 32) in 'SCR-030 price pane'; keep that anchor after relayout: do not centre it
- frame 'SCR-038∕anchored-place': 'board marker · contract pending' anchored top-left at (720, 36) in 'SCR-030 price pane'; keep that anchor after relayout: do not centre it
- root 'E19-D02 / 10 period-flow' at (16000, 3200): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 912 px) ends inside the root (h 1878); raise the root's h to max(annotation end, footer end) + 80 if not
- centring: no block on this board is re-centred by default; only a block a check in this list names 'centred horizontally and vertically' is centred (on the axes it names); every other block keeps the anchor and x, y given here (frames top-left on the grid, the annotation column top-left right of the frames, board markers top-left in their frame)
- frame 'SCR-038∕period-menu': read back 1280 x 800 at (80, 80) (top-left anchor); clip on, no child spills
- frame 'SCR-038∕fixed-range-drag': read back 1280 x 800 at (1440, 80) (top-left anchor); clip on, no child spills
- frame 'SCR-038∕anchored-place': read back 1280 x 800 at (80, 960) (top-left anchor); clip on, no child spills
- theme: the dark token set is active (greyscale wire); export docs/design/E19/img/E19-D02-10-period-flow.png; record the board id and the PNG size

## Readings (1)

- developing bracket: the open end is the value-area edge on the last price's side (PD-1 leaves the side unworded)

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 416 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Not drawn (1)

- W-33 "POC {price}, VAH {price}, VAL {price}" (spec L382): not drawn: announcement-only (the panel's polite region, latest value only, at most once per 2 s: §11 L344, R-4); the annotation's 'Levels (derived)' line carries the values it would announce — the text is binding

## Copy keys (42)

- "Session" (spec L53)
- "Fixed range" (spec L53)
- "Visible range" (spec L53)
- "Anchored" (spec L53)
- "Composite" (spec L53)
- "session" (spec L58)
- "fixed_range" (spec L213)
- "visible_range" (spec L214)
- "none — contract pending A-1" (spec L215)
- "composite" (spec L58)
- "a committed choice in the Period menu or SCR-039's radio" (spec L325)
- "{from, to, host}" (spec L62)
- "profile.period_changed" (spec L325)
- "a committed choice in the Input menu (volume / delta / TPO)" (spec L326)
- "profile.mode_changed" (spec L326)
- "the VA % stepper's commit (blur or `Enter`), never per key" (spec L327)
- "profile.va_percent_changed" (spec L327)
- W-2: "Aligned to {symbol} · {interval}" (spec L351) filled from the world
- W-1: "Profile: BTCUSDT" (spec L350)
- W-4: "Developing · as of {HH:MM} UTC" (spec L353) filled from the world
- "Period" (spec L135)
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
- W-30: "Shift-drag on the chart to choose a range" (spec L379)
- W-31: "Click a bar to anchor the profile" (spec L380)
- "contract pending A-1" (spec L53)

## Copy gaps (5)

- "Each word's kind (board only)": board marker title (kit); §5.1
- "30m": the bound chart's interval word (the world's 30-minute bars, or n of them as one candle), drawn in the chart header and filling W-2's {interval}
- "Shift-drag (PROPOSED)": board marker label (kit), §10.2
- "anchor": board marker label (kit), §10.2
- "Anchored": board marker title (kit), the §5.1 word

## Fallbacks (6)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- wire stand-in: a focused control or row carries a 2 px color.text.primary outline (the system outline, §11 R2); the focus-ring token is hi-fi (E19-D03)
- kit choice: a board marker box ('board marker · …', 1 px color.border.default outline on color.surface.canvas) names a measurement, a gesture or an order, never product UI
- wire stand-in: the HVN / LVN glyphs are the characters '>' / '<' of the §3.1 sketch's legend in type.num.sm; their shapes are E19-D03's (PD-3)
- kit choice: the chart beside the panel is a plain SCR-030 price pane (grey candles, grid, price axis, time axis) for alignment only; candle direction is not encoded (greyscale wire, §2)
- kit choice: the terminal's TopBar and StatusBar are wordless placeholders (E10's chrome, not this spec's); the app's global chrome band is the only environment carrier (R-1) and no frame draws one

## Icons (5)

- check: this kit's local-icons.js (not in the repo's run/local-icons.js)
- chevron-down: this kit's local-icons.js (not in the repo's run/local-icons.js)
- arrow-down: the repo's run/local-icons.js
- arrow-up: the repo's run/local-icons.js
- info: this kit's local-icons.js (not in the repo's run/local-icons.js)

## Sources (3)

- spec E19-D02.md md5 40b8a21b (the boards PR's text: §0 drawn, §18 As built; read via checkout; §0 L81; BQ list RULED, comment 6576655478)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: the shared token-sync.json (no local rows); wire tokens only (§2)

## Tokens (20)

- color.text.primary
- size.icon.sm
- type.ui.caption
- space.inset.xs
- radius.control
- border.thick
- type.ui.label
- color.text.secondary
- space.stack.xs
- space.inset.sm
- color.surface.canvas
- border.hairline
- radius.card
- color.surface.raised
- color.border.default
- type.num.sm
- color.text.tertiary
- color.surface.overlay
- space.stack.sm
- space.inset.lg
