# E19-D02 / 09 presets-clamp-viewas

File `E19-D02 boards`, page `E19-D02`; export `docs/design/E19/img/E19-D02-09-presets-clamp-viewas.png`; sheet `09-presets-clamp-viewas.json` (validated); theme dark.

Board 09 of 10 (§0 L80: SCR-038/presets-entry, SCR-038/presets-view-as, SCR-039/row-size-clamped, SCR-039/view-as). Grid (12000, 3200); 3280 x 1878 px; "page E19-D02 · board 09 · r1".

## Frames

- `SCR-038∕presets-entry` (1280 x 800)
- `SCR-038∕presets-view-as` (1280 x 800)
- `SCR-039∕row-size-clamped` (1280 x 800)
- `SCR-039∕view-as` (1280 x 800)

## Validator and size

- `09-presets-clamp-viewas.json: 0 errors, 70 warnings, 56 sections, 257550 bytes` (exit 0)
- 56 sections, 257550 bytes

## Live checks (11)

- frame 'SCR-038∕presets-view-as': 'board marker · announced on Enter ∕ Space' anchored top-left at (620, 92) in the frame; keep that anchor after relayout: do not centre it
- frame 'SCR-039∕row-size-clamped': 'CMP-043 dialog' (760 x 640) centred horizontally and vertically in the frame at (260, 80) = ((1280 - 760) / 2, (800 - 640) / 2); after relayout re-centre it on both axes if its size changed
- frame 'SCR-039∕view-as': 'CMP-043 dialog' (760 x 640) centred horizontally and vertically in the frame at (260, 80) = ((1280 - 760) / 2, (800 - 640) / 2); after relayout re-centre it on both axes if its size changed
- root 'E19-D02 / 09 presets-clamp-viewas' at (12000, 3200): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 1248 px) ends inside the root (h 1878); raise the root's h to max(annotation end, footer end) + 80 if not
- centring: no block on this board is re-centred by default; only a block a check in this list names 'centred horizontally and vertically' is centred (on the axes it names); every other block keeps the anchor and x, y given here (frames top-left on the grid, the annotation column top-left right of the frames, board markers top-left in their frame)
- frame 'SCR-038∕presets-entry': read back 1280 x 800 at (80, 80) (top-left anchor); clip on, no child spills
- frame 'SCR-038∕presets-view-as': read back 1280 x 800 at (1440, 80) (top-left anchor); clip on, no child spills
- frame 'SCR-039∕row-size-clamped': read back 1280 x 800 at (80, 960) (top-left anchor); clip on, no child spills
- frame 'SCR-039∕view-as': read back 1280 x 800 at (1440, 960) (top-left anchor); clip on, no child spills
- theme: the dark token set is active (greyscale wire); export docs/design/E19/img/E19-D02-09-presets-clamp-viewas.png; record the board id and the PNG size

## Readings (1)

- developing bracket: the open end is the value-area edge on the last price's side (PD-1 leaves the side unworded)

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 416 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Not drawn (1)

- W-38 "Profile settings applied." (spec L387): not drawn: announcement-only (Save applies and closes the dialog); named in this board's annotation notes only, on no frame — the text is binding

## Copy keys (67)

- W-32: "Modified" (spec L381)
- "Session value" (spec L302)
- "Save preset…" (spec L113)
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
- W-15: "Read-only while viewing as {user}." (spec L364) filled from the world
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
- W-25: "Row size clamped to 1 tick ({tick}) from {entered} — the instrument's minimum." (spec L374) filled from the world
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

## Copy gaps (7)

- the user's presets Preset A, Preset B: synthetic names (kit choice; E19-D04 owns presets)
- "30m": the bound chart's interval word (the world's 30-minute bars, or n of them as one candle), drawn in the chart header and filling W-2's {interval}
- "Sam": W-15's {user}, a synthetic display name (no account identifier, R-1)
- "announced on Enter / Space": board marker title (kit)
- "announced on Enter / Space": the kit's marker title for a string a screen reader hears (board marker)
- the Period radios' one-line descriptions are `14`:1025's, unworded in this spec: each is a grey placeholder line (wire convention), linked by aria-describedby
- "Presets": the VA % preset chips' label (§8.1 'presets 68 / 70 / 80')

## Fallbacks (8)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- wire stand-in: a focused control or row carries a 2 px color.text.primary outline (the system outline, §11 R2); the focus-ring token is hi-fi (E19-D03)
- wire stand-in: the HVN / LVN glyphs are the characters '>' / '<' of the §3.1 sketch's legend in type.num.sm; their shapes are E19-D03's (PD-3)
- kit choice: the chart beside the panel is a plain SCR-030 price pane (grey candles, grid, price axis, time axis) for alignment only; candle direction is not encoded (greyscale wire, §2)
- kit choice: the terminal's TopBar and StatusBar are wordless placeholders (E10's chrome, not this spec's); the app's global chrome band is the only environment carrier (R-1) and no frame draws one
- kit choice: a string a screen reader hears (an accessible name, a description, a polite announcement) is drawn for the board as caption text in a bordered 'board marker' box (not on screen in the product)
- kit choice: a board marker box ('board marker · …', 1 px color.border.default outline on color.surface.canvas) names a measurement, a gesture or an order, never product UI
- kit choice: the modal backdrop (background inert, §8.1) is not drawn as a tint: a greyscale wire has no scrim token among §2's wire tokens; the dialog sits over the unchanged window

## Icons (6)

- chevron-down: this kit's local-icons.js (not in the repo's run/local-icons.js)
- arrow-down: the repo's run/local-icons.js
- arrow-up: the repo's run/local-icons.js
- locked: the repo's run/local-icons.js
- info: this kit's local-icons.js (not in the repo's run/local-icons.js)
- check: this kit's local-icons.js (not in the repo's run/local-icons.js)

## Sources (3)

- spec E19-D02.md md5 40b8a21b (the boards PR's text: §0 drawn, §18 As built; read via checkout; §0 L80; BQ list RULED, comment 6576655478)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: the shared token-sync.json (no local rows); wire tokens only (§2)

## Tokens (24)

- type.ui.caption
- color.text.primary
- space.inset.xs
- radius.control
- color.border.default
- type.ui.label
- color.text.secondary
- space.inset.sm
- size.icon.sm
- color.surface.raised
- border.hairline
- type.num.sm
- color.surface.canvas
- border.thick
- space.stack.xs
- color.text.tertiary
- color.surface.overlay
- radius.card
- radius.badge
- space.stack.sm
- space.inset.md
- space.inset.xl
- radius.dialog
- space.inset.lg
