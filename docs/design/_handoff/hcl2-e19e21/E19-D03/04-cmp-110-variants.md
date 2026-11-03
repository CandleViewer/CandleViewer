# E19-D03 / 04 cmp-110-variants

File `E19-D03 boards`, page `E19-D03`; export `docs/design/E19/img/E19-D03-04-cmp-110-variants.png`; sheet `04-cmp-110-variants.json` (validated); theme dark.

Board 04 of ten (§0 L77: CMP-110 ref frames (volume, delta, TPO, split, every level state); SCR-038/zero-delta-dark). Grid (22800, 0); 2880 x 2136 px; "page E19-D03 · board 04 · r1".

## Frames

- `CMP-110 · ProfileBar — ref frame (volume)` (dark, 880 x 440)
- `CMP-110 · ProfileBar — ref frame (delta)` (dark, 880 x 440)
- `CMP-110 · ProfileBar — ref frame (tpo)` (dark, 880 x 440)
- `CMP-110 · ProfileBar — ref frame (split)` (dark, 880 x 440)
- `CMP-110 · ProfileBar — ref frame (greyscale)` (dark, 880 x 880)
- `SCR-038∕zero-delta-dark` (dark, 1280 x 800)

## Validator and size

- `04-cmp-110-variants.json: 0 errors, 9 warnings, 38 sections, 106307 bytes` (exit 0)
- 38 sections, 106307 bytes

## Live checks (10)

- root 'E19-D03 / 04 cmp-110-variants' at (22800, 0): read back the name exactly after the first section call; size 2880 x 2136
- after touchTexts + relayout: the annotation column (estimated 1251 px) ends inside the root (h 2136); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'CMP-110 · ProfileBar — ref frame (volume)': read back 880 x 440 at (80, 80); clip on, no child spills
- frame 'CMP-110 · ProfileBar — ref frame (delta)': read back 880 x 440 at (1040, 80); clip on, no child spills
- frame 'CMP-110 · ProfileBar — ref frame (tpo)': read back 880 x 440 at (80, 600); clip on, no child spills
- frame 'CMP-110 · ProfileBar — ref frame (split)': read back 880 x 440 at (1040, 600); clip on, no child spills
- frame 'CMP-110 · ProfileBar — ref frame (greyscale)': read back 880 x 880 at (80, 1120); clip on, no child spills
- frame 'SCR-038∕zero-delta-dark': read back 1280 x 800 at (1040, 1120); clip on, no child spills
- local tokens: create the sets of local-tokens.json ('E19-D03 local · dark', '· light', '· hc', each active only in its theme) before the first section call; color.tpo.letter and color.tpo.initialbalance bind them
- export docs/design/E19/img/E19-D03-04-cmp-110-variants.png; record the board id and the PNG size

## Readings (2)

- R-K5: the forced-colours specimen binds every ink to color.text.primary (CanvasText) on color.surface.canvas (Canvas), §2.4; greyscale is the export's Rec. 601 transform (board 05); high contrast resolves the profile tokens as dark (§2.1)
- R-K3: the bracket's developing edge (no end cap, §7.2) is the value-area edge on the last price's side

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 438 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (55)

- D02 W-2: "Aligned to {symbol} · {interval}" (D02 L351) filled from the world
- W-10: "Developing · as of {HH:MM} UTC" (spec L391) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "Period" (spec L261)
- "Visible range" (spec L263)
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
- W-12: "Rows merged: {k} levels per row" (spec L393) filled from the world
- "HVN" (spec L124)
- "LVN" (spec L124)
- "Single prints" (spec L200)
- W-2: "{k} hidden" (spec L383) filled from the world
- W-6: "Show tested" (spec L387)
- W-13: "Outside VA" (spec L394)
- W-13: "In VA" (spec L394)
- "POC" (spec L5)
- W-18: "point of control" (spec L399)
- W-17: "high-volume node" (spec L398)
- W-17: "low-volume node" (spec L398)
- W-4: "nPOC {date}" (spec L385) filled from the world
- W-14: "(estimated)" (spec L395)
- D02 W-34: "{level word} {price}: volume {v}, delta {d}, in value area" (D02 L383) filled from the world
- "CMP-110 · ProfileBar — ref frame (volume)" (hand-off L28)
- W-9: "Net delta zero" (spec L390)
- W-9: "No trades at this price" (spec L390)
- "CMP-110 · ProfileBar — ref frame (delta)" (hand-off L29)
- W-15: "single print" (spec L396)
- "CMP-110 · ProfileBar — ref frame (tpo)" (hand-off L31)
- "CMP-110 · ProfileBar — ref frame (split)" (hand-off L30)
- "every level state" (spec L77)
- "Default" (spec L223)
- "value area" (spec L118)
- "naked POC" (spec L205)
- "single print" (spec L59)
- "untraded" (spec L56)
- "zero delta" (spec L203)
- "estimated" (spec L56)
- "focused" (spec L175)
- "merged" (spec L7)
- §2.3 L160: the ratios table, cells verbatim (normal / greyscale / deuteranopia / protanopia / tritanopia)
- "normal / greyscale / deuteranopia / protanopia / tritanopia" (spec L158)
- "CMP-110 · ProfileBar — ref frame (greyscale)" (hand-off L32)
- "Session" (spec L263)
- "Delta" (spec L217)
- "BTCUSDT" (spec L62)
- "VAH" (spec L120)
- "VAL" (spec L120)

## Copy gaps (9)

- "30m": the bound chart's interval word (kit world: 30-minute bars), filling D02 W-2's {interval}
- "State", "Specimen", "Mirror words": the ref frame's column heads (board labels, kit form)
- "delta +0.858": D02 W-34's delta clause, filled
- "delta −0.552": D02 W-34's delta clause, filled
- "ABCDEFGHIKLMNOPQRSTUVWX": the row's letters as the mirror reads them (§6.2)
- "ABDEFGIJKMNPQRSTUVWXYZabcdeflmnrstv": the row's letters as the mirror reads them (§6.2)
- "buy 24.972, sell 24.881": the mirror's buy and sell numbers (§3 row 2), filled
- "every level state (§4.2 L223)": the strip's heading: §0's words and the cite (board label)
- "forced colours: every ink CanvasText, the side by order and ▲ / ▼, the hatch as Canvas lines (§2.4); greyscale and high contrast: the table": a summary line of §2.3 / §2.4 (board subtitle)

## Fallbacks (5)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit stand-in: the engine bakes the HVN / LVN triangles (6 × 6 px) into the bar instance (§3 rows 5, 6); the board draws them as the characters ▶ / ◀ in type.num.xs (no triangle shape in the node set)
- kit stand-in: pattern.hatch.estimated (45°, 2 px pitch, 30 % over the fill, D05E11:313) is a registered pattern id, not a token; the board draws 1 px color.surface.canvas 'hatch line · ' strokes at an 8 px pitch over each approximated bar (rotated 45° by the post-step), clipped to the bar
- token-sync.json has no color.chart.focus.ring; SD:715 aliases it to color.focus.ring (§2.1), so the canvas ring binds color.focus.ring
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the chart beside the panel is a plain SCR-030 price pane (candles, grid, price axis) for alignment only

## Sources (4)

- spec E19-D03.md md5 928db4e4 and hand-off md5 fb2077ba (§0 L77; RULED comment 6580374205)
- D02 E19-D02.md md5 1299df3b at bed73afaa (read via git show bed73afaa; re-pinned when PR #5487 merges)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.tpo.*, PROPOSED, §2.1)

## Tokens (36)

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
- color.profile.bar
- color.profile.poc
- color.focus.ring
- border.focus
- color.text.tertiary
- type.ui.heading-sm
- space.inset.lg
- color.surface.app
- color.buy.default
- color.sell.default
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.up
- color.candle.down
- space.stack.sm
