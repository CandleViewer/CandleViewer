# E19-D02 / 08 settings-compact

File `E19-D02 boards`, page `E19-D02`; export `docs/design/E19/img/E19-D02-08-settings-compact.png`; sheet `08-settings-compact.json` (validated); theme dark.

Board 08 of 10 (§0 L79: SCR-039/compact, SCR-039/va-invalid, SCR-039/end-before-start, SCR-039/lookback-warning). Grid (8000, 3200); 3280 x 1878 px; "page E19-D02 · board 08 · r1".

## Frames

- `SCR-039∕compact` (1280 x 800)
- `SCR-039∕va-invalid` (1280 x 800)
- `SCR-039∕end-before-start` (1280 x 800)
- `SCR-039∕lookback-warning` (1280 x 800)

## Validator and size

- `08-settings-compact.json: 0 errors, 104 warnings, 72 sections, 342482 bytes` (exit 0)
- 72 sections, 342482 bytes

## Live checks (12)

- frame 'SCR-039∕compact': 'CMP-043 dialog' (760 x 640) centred horizontally and vertically in the frame at (260, 80) = ((1280 - 760) / 2, (800 - 640) / 2); after relayout re-centre it on both axes if its size changed
- frame 'SCR-039∕va-invalid': 'CMP-043 dialog' (760 x 640) centred horizontally and vertically in the frame at (260, 80) = ((1280 - 760) / 2, (800 - 640) / 2); after relayout re-centre it on both axes if its size changed
- frame 'SCR-039∕end-before-start': 'CMP-043 dialog' (760 x 640) centred horizontally and vertically in the frame at (260, 80) = ((1280 - 760) / 2, (800 - 640) / 2); after relayout re-centre it on both axes if its size changed
- frame 'SCR-039∕lookback-warning': 'CMP-043 dialog' (760 x 640) centred horizontally and vertically in the frame at (260, 80) = ((1280 - 760) / 2, (800 - 640) / 2); after relayout re-centre it on both axes if its size changed
- root 'E19-D02 / 08 settings-compact' at (8000, 3200): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 1190 px) ends inside the root (h 1878); raise the root's h to max(annotation end, footer end) + 80 if not
- centring: no block on this board is re-centred by default; only a block a check in this list names 'centred horizontally and vertically' is centred (on the axes it names); every other block keeps the anchor and x, y given here (frames top-left on the grid, the annotation column top-left right of the frames, board markers top-left in their frame)
- frame 'SCR-039∕compact': read back 1280 x 800 at (80, 80) (top-left anchor); clip on, no child spills
- frame 'SCR-039∕va-invalid': read back 1280 x 800 at (1440, 80) (top-left anchor); clip on, no child spills
- frame 'SCR-039∕end-before-start': read back 1280 x 800 at (80, 960) (top-left anchor); clip on, no child spills
- frame 'SCR-039∕lookback-warning': read back 1280 x 800 at (1440, 960) (top-left anchor); clip on, no child spills
- theme: the dark token set is active (greyscale wire); export docs/design/E19/img/E19-D02-08-settings-compact.png; record the board id and the PNG size

## Readings (1)

- developing bracket: the open end is the value-area edge on the last price's side (PD-1 leaves the side unworded)

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 416 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Not drawn (4)

- W-36 "Input: {input}" (spec L385): not drawn: announcement-only (an Input change, announced once, §11 L344) — the text is binding
- W-37 "Value area: {n} %" (spec L386): not drawn: announcement-only (a VA % change, announced once, §11 L344) — the text is binding
- W-38 "Profile settings applied." (spec L387): not drawn: announcement-only (Save applies and closes the dialog); named in this board's annotation notes only, on no frame — the text is binding
- W-39 "{n} problems to fix: {first error}" (spec L388): not drawn: announcement-only (one polite count on Save with several errors, §8.3 L298); SCR-039/va-invalid draws one error — the text is binding

## Copy keys (74)

- W-2: "Aligned to {symbol} · {interval}" (spec L351) filled from the world
- W-1: "Profile: BTCUSDT" (spec L350)
- W-4: "Developing · as of {HH:MM} UTC" (spec L353) filled from the world
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
- "Fixed range" (spec L53)
- "Visible range" (spec L53)
- "Anchored" (spec L53)
- "Composite" (spec L53)
- "anchor" (spec L5)
- "UTC day" (spec L212)
- "funding 8 h" (spec L277)
- "custom HH:MM" (spec L277)
- "One per session, side by side" (spec L218)
- "Delta" (spec L54)
- "TPO" (spec L5)
- "Row size (ticks)" (spec L278)
- "Value area %" (spec L278)
- "68 / 70 / 80" (spec L223)
- "Single step" (spec L287)
- "Two-row TPO" (spec L287)
- W-28: "Single step: grows the value area one row at a time toward the heavier side." (spec L377)
- W-28: "Two-row TPO: compares two rows on each side at a time, the textbook TPO method." (spec L377)
- "Rows and value area" (spec L278)
- "Levels and overlays" (spec L279)
- "show developing value area" (spec L279)
- "extend POC / VA lines to the right" (spec L279)
- "HVN / LVN marking" (spec L279)
- "naked POC, nearest N" (spec L279)
- "VWAP ±1σ / ±2σ" (spec L279)
- "TPO period" (spec L280)
- "min" (spec L38)
- "TPO letter size" (spec L163)
- "initial balance periods" (spec L280)
- "single prints" (spec L163)
- "per-period colour (a slot; hi-fi E19-D03)" (spec L281)
- "Appearance" (spec L281)
- "split" (spec L5)
- "merged bars" (spec L281)
- "combined volume + delta view" (spec L281)
- "Profile settings" (spec L267)
- "Save" (spec L113)
- "Reset" (spec L271)
- "Cancel" (spec L271)
- W-22: "Value area must be between 50 and 95 %." (spec L371)
- "duration" (spec L213)
- "Start" (spec L7)
- "End" (spec L295)
- W-23: "End must be after start." (spec L372)
- "look-back sessions" (spec L277)
- "session" (spec L58)
- "day" (spec L58)
- "week" (spec L277)
- "custom range" (spec L277)
- W-24: "Recorded history covers {n} of {m} sessions; the profile is built from what exists." (spec L373) filled from the world
- W-21: "Covered: {from} – {to} · {n} of {m} sessions" (spec L370) filled from the world

## Copy gaps (5)

- "30m": the bound chart's interval word (the world's 30-minute bars, or n of them as one candle), drawn in the chart header and filling W-2's {interval}
- the Period radios' one-line descriptions are `14`:1025's, unworded in this spec: each is a grey placeholder line (wire convention), linked by aria-describedby
- "Presets": the VA % preset chips' label (§8.1 'presets 68 / 70 / 80')
- start / end values: the kit's 'DD Mon HH:MM' UTC form (no format in §8)
- date form "10 Oct" (day, month) for W-21's {from} / {to} and W-6's days: §12 gives no format

## Fallbacks (5)

- kit choice: the modal backdrop (background inert, §8.1) is not drawn as a tint: a greyscale wire has no scrim token among §2's wire tokens; the dialog sits over the unchanged window
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- wire stand-in: the HVN / LVN glyphs are the characters '>' / '<' of the §3.1 sketch's legend in type.num.sm; their shapes are E19-D03's (PD-3)
- kit choice: the chart beside the panel is a plain SCR-030 price pane (grey candles, grid, price axis, time axis) for alignment only; candle direction is not encoded (greyscale wire, §2)
- kit choice: the terminal's TopBar and StatusBar are wordless placeholders (E10's chrome, not this spec's); the app's global chrome band is the only environment carrier (R-1) and no frame draws one

## Icons (6)

- chevron-down: this kit's local-icons.js (not in the repo's run/local-icons.js)
- arrow-down: the repo's run/local-icons.js
- arrow-up: the repo's run/local-icons.js
- check: this kit's local-icons.js (not in the repo's run/local-icons.js)
- danger: this kit's local-icons.js (not in the repo's run/local-icons.js)
- warning: this kit's local-icons.js (not in the repo's run/local-icons.js)

## Sources (3)

- spec E19-D02.md md5 40b8a21b (the boards PR's text: §0 drawn, §18 As built; read via checkout; §0 L79; BQ list RULED, comment 6576655478)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: the shared token-sync.json (no local rows); wire tokens only (§2)

## Tokens (23)

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
- radius.badge
- space.stack.sm
- space.inset.md
- space.inset.xl
- color.surface.overlay
- radius.dialog
- border.thick
- space.inset.lg
