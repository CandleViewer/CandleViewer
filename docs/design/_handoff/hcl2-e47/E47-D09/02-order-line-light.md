# E47-D09 / 02 order-line-light

File `E47-D09 boards`, page `E47-D09`; export `docs/design/E47/img/E47-D09-02-order-line-light.png`; sheet `02-order-line-light.json` (validated); theme light.

Board 02 of ten (§0 L69: light twin of 01). Grid (6000, 0); 4640 x 1880 px; "page E47-D09 · board 02 · r1".

## Frames

- `order-line∕selected · light`
- `order-line∕pending · light`
- `order-line∕refused · light`
- `order-line∕confirm · light`
- `order-line∕cancelled · light`

## Validator and size

- `02-order-line-light.json: 0 errors, 2 warnings, 91 sections, 259830 bytes` (exit 0)
- 91 sections, 259830 bytes

## Live checks (10)

- modal: re-centre 'CMP-044 confirm · amend' after relayout (estimated 480 x 181 px)
- root 'E47-D09 / 02 order-line-light' at (6000, 0): read back the name exactly after the first section call; size 4640 x 1880
- after touchTexts + relayout: the annotation column (estimated 1330 px) ends inside the root (h 1880); set the root's h to max(column end, footer end) + 80
- frame 'order-line∕selected · light': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'order-line∕pending · light': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'order-line∕refused · light': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'order-line∕confirm · light': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'order-line∕cancelled · light': read back 1280 x 800 at (1440, 960); clip on, no child spills
- theme: activate the light token set before exporting board 02 (twin of 01); read back one bound fill (color.surface.canvas) as the light value
- export docs/design/E47/img/E47-D09-02-order-line-light.png: every frame is 1280 x 800; record the board id and the PNG size

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

- spec docs/design/E47/E47-D09.md md5 3f1952f3 (§0 L69); hand-off docs/design/E47/E47-D09-handoff.md md5 97611aba (§H L105); registry apps/web/src/keymap/keymap.json md5 eb409e85 and apps/web/src/keymap/reserved-keys.json md5 5683c37f; tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; read at 260bb0caf

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
