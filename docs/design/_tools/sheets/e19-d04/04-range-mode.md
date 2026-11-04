# E19-D04 / 04 range-mode

File `E19-D04 boards`, page `E19-D04`; export `docs/design/E19/img/E19-D04-04-range-mode.png`; sheet `04-range-mode.json` (validated); theme dark.

Board 04 of ten (§0 L74: SCR-038/range-mode-dark, SCR-038/range-mode-light, SCR-038/range-handles-dark). Grid (22800, 0); 3280 x 1878 px; "page E19-D04 · board 04 · r1".

## Frames

- `SCR-038∕range-mode-dark` (dark, 1280 x 800)
- `SCR-038∕range-mode-light` (light, 1280 x 800)
- `SCR-038∕range-handles-dark` (dark, 1280 x 800)

## Validator and size

- `04-range-mode.json: 0 errors, 25 warnings, 26 sections, 105876 bytes` (exit 0)
- 26 sections, 105876 bytes

## Live checks (7)

- root 'E19-D04 / 04 range-mode' at (22800, 0): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 1172 px) ends inside the root (h 1878, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕range-mode-dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-038∕range-mode-light': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-038∕range-handles-dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- export docs/design/E19/img/E19-D04-04-range-mode.png under the dark set; record the board id and the PNG size
- kit reading R-K1: export board 04 a second time under the light set as docs/design/E19/img/E19-D04-04-range-mode-light.png; read back one bound fill (color.surface.raised) as the light value; its '-light' frame is read from that export, its '-dark' frames from docs/design/E19/img/E19-D04-04-range-mode.png

## Readings (2)

- R-K2: a range's legend words are its two times joined as W-26 joins them, "{start} to {end} UTC" (R-2, R-7); {start} / {end} fill as YYYY-MM-DD HH:MM and the deck's own "UTC" closes the pair, so a sentence never reads "UTC UTC"
- a developing profile's open bracket edge (no cap) is the value-area edge on the last price's side (the E19-D03 kit's R-K3)

## Derivations (1)

- world: BTCUSDT 5m bars from 2026-11-02 00:00 UTC to the clock 2026-11-02 14:30 UTC, one walk seeded 439 (the issue number; drift redrawn every 24 bars), prices at the fixture's tick 0.10, sizes at its qty step 0.001; row size 100 ticks unless a preset says otherwise; the rectangle's price edges are the low / high of the bars it spans

## Spec gaps (0)

## Deviations (0)

## Copy keys (26)

- "Fixed range" (spec L51)
- W-23: "Drag on the chart to choose a range · Esc to stop" (spec L343)
- W-22: "Profile range" (spec L342)
- D02 W-2: "Aligned to {symbol} · {interval}" (D02 L351) filled from the world
- D03 W-10: "Developing · as of {HH:MM} UTC" (D03 L391) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- W-1: "Presets" (spec L321)
- "Period" (spec L31)
- "Input" (spec L9)
- "Volume" (D03 L5)
- "VA%" (D02 L135)
- "Row" (spec L235)
- "VWAP" (spec L51)
- D02 W-29: "Histogram" (D02 L378)
- D02 W-29: "Table" (D02 L378)
- "Settings" (D02 L100)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "HVN" (spec L125)
- "LVN" (spec L125)
- D03 W-6: "Show tested" (D03 L387)
- "BTCUSDT" (spec L67)
- "POC" (spec L551)
- "VAH" (spec L551)
- "VAL" (D03 L120)
- D03 W-11: "Final" (D03 L392)
- W-26: "Profile range {start} to {end} UTC." (spec L346) filled from the world

## Copy gaps (3)

- "5m": the bound chart's interval word (kit world: 5-minute bars)
- "polite announcement (once, on entering the mode)": the kit's marker label for a string a screen reader hears (board marker)
- "polite announcement (once per commit)": the kit's marker label for a string a screen reader hears (board marker)

## Fallbacks (6)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit stand-in: a CSS cursor (§5's keywords) is drawn as a small shape (crosshair: two 1 px strokes; ew-resize / ns-resize: a bar with two end ticks; grab / grabbing / move / pointer / default: a 10 px glyph box) with its keyword beside it in type.num.sm — the shape is a board marker, the keyword binds
- kit stand-in (the E19-D03 kit's): the engine bakes the HVN / LVN triangles into the bar instance; the board draws them as the characters ▶ / ◀ in type.num.xs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the bound chart is a plain SCR-030 price pane (candles, grid, price axis); its status row draws only the chips these flows touch (the tool chip, the feed chip on the stale frame) — no environment badge or control anywhere (R-1, C-2.11)
- kit choice: a string a screen reader hears (an accessible name, a polite announcement) is drawn for the board as caption text in a bordered 'visually hidden' box (not on screen in the product)
- E14's handle language (§11): a color.text.primary dot in a color.border.strong ring, the glyph 8 px (D02E14 L287), its 24 × 24 target drawn only as a dashed board-marker outline where the target matters

## Sources (8)

- spec E19-D04.md md5 9e0d20c3 in this checkout (§0 L74; BQ ruling RULED, comment 6585044844)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; PR #5517 head; re-pinned when it merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via checkout; merge commit of PR #5487)
- D02E14 E14-D02.md md5 8560e306 at the base 95a625b09
- D07E14 E14-D07.md md5 697232d6 at the base 95a625b09
- D02E17 E17-D02.md md5 cb9a4d78 at the base 95a625b09
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json only (§11: shipped names, nothing new)

## Tokens (34)

- type.ui.caption
- color.text.primary
- space.inset.sm
- space.inset.xs
- radius.badge
- color.surface.raised
- color.border.strong
- border.hairline
- type.ui.label
- color.text.secondary
- size.icon.sm
- radius.control
- color.action.secondary.default
- color.border.default
- type.num.sm
- color.surface.sunken
- color.surface.selected
- space.stack.xs
- color.profile.valuearea
- color.surface.canvas
- type.num.xs
- color.focus.ring
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.down
- color.candle.up
- color.profile.bar
- color.profile.poc
- color.text.tertiary
- color.surface.app
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
