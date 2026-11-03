# E19-D03 / 08 rays-npoc-tooltip

File `E19-D03 boards`, page `E19-D03`; export `docs/design/E19/img/E19-D03-08-rays-npoc-tooltip.png`; sheet `08-rays-npoc-tooltip.json` (validated); theme dark.

Board 08 of ten (§0 L81: SCR-038/extend-lines-dark, SCR-038/npoc-capped-dark, SCR-038/npoc-tested-dark, SCR-038/poc-tooltip-dark, SCR-038/edge-va-spans-view-dark). Grid (15200, 5600); 3280 x 2776 px; "page E19-D03 · board 08 · r1".

## Frames

- `SCR-038∕extend-lines-dark` (dark, 1280 x 800)
- `SCR-038∕npoc-capped-dark` (dark, 1280 x 800)
- `SCR-038∕npoc-tested-dark` (dark, 1280 x 800)
- `SCR-038∕poc-tooltip-dark` (dark, 1280 x 800)
- `SCR-038∕edge-va-spans-view-dark` (dark, 1280 x 800)

## Validator and size

- `08-rays-npoc-tooltip.json: 0 errors, 30 warnings, 53 sections, 267044 bytes` (exit 0)
- 53 sections, 267044 bytes

## Live checks (9)

- root 'E19-D03 / 08 rays-npoc-tooltip' at (15200, 5600): read back the name exactly after the first section call; size 3280 x 2776
- after touchTexts + relayout: the annotation column (estimated 1142 px) ends inside the root (h 2776); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-038∕extend-lines-dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-038∕npoc-capped-dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-038∕npoc-tested-dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-038∕poc-tooltip-dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- frame 'SCR-038∕edge-va-spans-view-dark': read back 1280 x 800 at (80, 1840); clip on, no child spills
- local tokens: create the sets of local-tokens.json ('E19-D03 local · dark', '· light', '· hc', each active only in its theme) before the first section call; color.tpo.letter and color.tpo.initialbalance bind them
- export docs/design/E19/img/E19-D03-08-rays-npoc-tooltip.png; record the board id and the PNG size

## Readings (4)

- R-K3: the bracket's developing edge (no end cap, §7.2) is the value-area edge on the last price's side
- overlay bars: 30 % of the pane's plot width (365 px of 1216, §10.2 PROPOSED), from the pane's right edge toward the left; the price axis and its last-price label stay uncovered
- R-K6: where rows are under 12 px, a node glyph (▶ / ◀) whose 10 px line would touch the previous one of its kind is not drawn; the row keeps its bar and the mirror and the table carry the word
- edge-va-spans-view: the user's vertical zoom shows only the inner rows of the value area (kit view)

## Derivations (2)

- "POC 73,080.0": the example "POC {price}" (spec L285) with this frame's values
- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 438 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (36)

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
- D02 §3.2: "Profile · Visible range ▾ · Volume ▾ · Histogram │ Table · ⚙" (D02 L159)
- "Profile" (spec L5)
- "Visible range" (spec L263)
- "⚙" (D02 L159)
- W-4: "nPOC {date}" (spec L385) filled from the world
- W-21: "Hide {k}" (spec L402) filled from the world
- W-22: "Hide {k} older naked POCs" (spec L403) filled from the world
- W-5: "tested" (spec L386)
- W-1: "POC tie-break: closest to the period VWAP, then to the last price, then the lower price." (spec L382)
- D02 W-34: "{level word} {price}: volume {v}, delta {d}, in value area" (D02 L383) filled from the world
- D02 W-26: "VAH {price} ↑ above view" (D02 L375) filled from the world
- D02 W-26: "VAL {price} ↓ below view" (D02 L375) filled from the world

## Copy gaps (6)

- "30m": the bound chart's interval word (kit world: 30-minute bars), filling D02 W-2's {interval}
- "2h": the chart interval word (kit view: 2-hour candles over ten days)
- "pressed: every ray drawn (§5); the label, then the accessible name": the marker's label (board marker)
- "Enter on the POC row reads": the kit's marker label for a string a screen reader hears (board marker)
- "Enter on the POC row reads": the hidden-string marker label (board marker)
- "mirror": the kit's marker label for a string a screen reader hears (board marker)

## Fallbacks (6)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the chart beside the panel is a plain SCR-030 price pane (candles, grid, price axis) for alignment only
- kit stand-in: the engine bakes the HVN / LVN triangles (6 × 6 px) into the bar instance (§3 rows 5, 6); the board draws them as the characters ▶ / ◀ in type.num.xs (no triangle shape in the node set)
- kit stand-in: pattern.dashed.tested's geometry (1 px, dashed 4 / 3) drawn as 4 px dashes with 3 px gaps
- token-sync.json has no color.chart.focus.ring; SD:715 aliases it to color.focus.ring (§2.1), so the canvas ring binds color.focus.ring
- kit choice: a string a screen reader hears (an accessible name, the mirror's reading, a polite announcement) is drawn for the board as caption text in a bordered 'visually hidden' box (not on screen in the product)

## Sources (4)

- spec E19-D03.md md5 928db4e4 and hand-off md5 fb2077ba (§0 L81; RULED comment 6580374205)
- D02 E19-D02.md md5 1299df3b at bed73afaa (read via git show bed73afaa; re-pinned when PR #5487 merges)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.tpo.*, PROPOSED, §2.1)

## Tokens (39)

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
- size.icon
- color.text.tertiary
- color.border.strong
- color.focus.ring
- border.focus
- space.inset.md
- color.surface.overlay
- radius.card
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
