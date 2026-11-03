# E47-D09 / 01 order-line

File `E47-D09 boards`, page `E47-D09`; export `docs/design/E47/img/E47-D09-01-order-line.png`; sheet `01-order-line.json` (validated); theme dark.

Board 01 of ten (§0 L68: the grammar on a working stop: selected, pending (W-1), refused loosen (W-19) and wrong side (W-20), Enter through the confirm, Esc (W-2) (§4)). Grid (0, 0); 4640 x 1878 px; "page E47-D09 · board 01 · r1".

## Frames

- `order-line∕selected · dark`
- `order-line∕pending · dark`
- `order-line∕refused · dark`
- `order-line∕confirm · dark`
- `order-line∕cancelled · dark`

## Validator and size

- `01-order-line.json: 0 errors, 2 warnings, 91 sections, 259626 bytes` (exit 0)
- 91 sections, 259626 bytes

## Live checks (9)

- modal: re-centre 'CMP-044 confirm · amend' after relayout, both axes (measured 480 x 183 px, y 309)
- root 'E47-D09 / 01 order-line' at (0, 0): read back the name exactly after the first section call; size 4640 x 1878
- after touchTexts + relayout: the root's h 1878 is the measured max(column end, footer end) + 80 (annotation column estimated 1344 px); read it back
- frame 'order-line∕selected · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'order-line∕pending · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'order-line∕refused · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'order-line∕confirm · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'order-line∕cancelled · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E47/img/E47-D09-01-order-line.png: every frame is 1280 x 800; record the board id and the PNG size

## Readings (3)

- {object} in W-1 / W-2 is "Stop-loss", the SCR-063 row word for the working stop; the select announcement is built from §4's cell (the line, its price, "arrows adjust")
- the readout that follows the pending value (§2 Adjust) is drawn as the line's price tag on the axis; the label on the line carries the word "pending"
- W-19 and W-20 share the one refused frame (§H names both on it): W-20's case is drawn, W-19's key and string are a second callout

## G rows (1)

- D09-G4 (§19.2 L420): no trading-object roving stop exists on the chart for DE-01 and DE-04 (owner E31-D01, the trading layer)

## C rows (1)

- D09-C8 (§19.1 L401): refused (§4); D09-A13 to the 14 owner

## Spec gaps (0)

## Deviations (1)

- dialog width 480 px: a kit choice (no source gives CMP-044's width)

## Copy keys (6)

- W-5 (§16 L310, PROPOSED (the short form))
- W-1 (§16 L306, PROPOSED (short form: {price}))
- W-20 (§16 L325, PROPOSED)
- W-19 (§16 L324, PROPOSED (SCR-064's twin is sl.loosen.refused, D05E32:264))
- W-21 (§16 L326, PROPOSED (then accepted or rejected, once))
- W-2 (§16 L307, PROPOSED)

## Copy gaps (3)

- the select announcement "Stop-loss, 67,416.00, arrows adjust": §4 L191 gives its parts ("the line, its price, arrows adjust"), not a W-string (E47-D07 owns the words)
- SCR-063 column words "Order", "Symbol", "Side", "Qty", "Price", "Status" and the row words "Position", "Stop-loss", "Take-profit", "Open", "Working": the grid's own (`14`:1523), not this spec's
- the confirm dialog's words "Amend stop-loss", "Cancel", "Confirm" and its two data lines: the drop's own confirm (SCR-040's confirm choice, `14`:1030-1033; E31-D01 owns it, PROPOSED); no W-string

## Fallbacks (7)

- kit choice: the chart is drawn at 4 px per tick and 12 px per 1-minute bar; candles, axis labels and the profile are derived from the seeded series (every label = a price on the tick grid)
- kit choice: numbered stop markers, tags, outlines, arrows and callouts are annotation overlays in color.status.info.default (callouts on color.surface.overlay), never product UI; a callout quotes what is spoken (polite) or what a key does
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); SCR-012's rows 32 px (E10-D03 §6.1, D03E10:281: 32 compact, 40 comfortable); the shell bars keep E10's 48 px TopBar
- fallback (E47-D04's): border.panel.focus (= {border.focus}, `16`:88) is not in the token file: the focused panel's inset frame is a border.focus inner stroke in color.focus.ring and its header bar a 3 px color.focus.ring rect
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items, list rows of SCR-093) drawn as neutral placeholders; only what this spec names is drawn with words
- fallback: the renderer draws no dashed stroke: the pending line is 8 px segments with 4 px gaps of the line's own token (each segment a rect), always with its "pending" label (§13: never colour or a line style alone)
- fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim

## Sources (1)

- spec docs/design/E47/E47-D09.md md5 690029fa (§0 L68); hand-off docs/design/E47/E47-D09-handoff.md md5 d50c31f7 (§H L105); registry at 4c662fd5b apps/web/src/keymap/keymap.json md5 eb409e85 and apps/web/src/keymap/reserved-keys.json md5 5683c37f; tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (55)

- color.position.entry
- type.num.xs
- color.text.primary
- space.inset.xs
- color.surface.raised
- border.hairline
- radius.control
- color.position.tp
- color.position.sl
- border.thick
- color.surface.canvas
- color.focus.ring
- border.focus
- color.crosshair
- color.border.subtle
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.down
- color.candle.up
- type.ui.label
- color.text.inverse
- color.status.info.default
- radius.badge
- type.ui.caption
- space.stack.xs
- space.inset.sm
- color.surface.overlay
- color.text.secondary
- size.icon
- type.ui.body-strong
- type.ui.body
- type.num.base
- color.border.default
- color.surface.hover
- space.inset.md
- color.surface.selected
- color.surface.app
- color.env.live
- space.button.paddingX
- color.status.danger.subtle
- color.status.danger.strong
- space.inset.lg
- color.action.secondary.default
- color.text.on-action
- color.action.primary.default
- type.ui.heading-md
- radius.dialog
- space.dialog.padding
- space.stack.md
- opacity.scrim
- color.surface.sunken
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
