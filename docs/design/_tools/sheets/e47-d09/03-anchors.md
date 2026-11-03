# E47-D09 / 03 anchors

File `E47-D09 boards`, page `E47-D09`; export `docs/design/E47/img/E47-D09-03-anchors.png`; sheet `03-anchors.json` (validated); theme dark.

Board 03 of ten (§0 L70: a drawing's anchor nudge and the "Edit values…" fields; a profile's anchor range (DE-07, DE-08; F-10, F-03)). Grid (12000, 0); 4640 x 1008 px; "page E47-D09 · board 03 · r1".

## Frames

- `drawing∕anchor-nudge · dark`
- `drawing∕edit-values · dark`
- `profile∕anchor-range · dark`

## Validator and size

- `03-anchors.json: 0 errors, 1 warnings, 48 sections, 152172 bytes` (exit 0)
- 48 sections, 152172 bytes

## Live checks (6)

- root 'E47-D09 / 03 anchors' at (12000, 0): read back the name exactly after the first section call; size 4640 x 1008
- after touchTexts + relayout: the root's h 1008 is the measured max(column end, footer end) + 80 (annotation column estimated 886 px); read it back
- frame 'drawing∕anchor-nudge · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'drawing∕edit-values · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'profile∕anchor-range · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D09-03-anchors.png: every frame is 1280 x 800; record the board id and the PNG size

## Readings (2)

- board 03's drawing is a Rectangle (two anchors, a `14`:958 tool) so both anchors and the time + price pairs show on one shape; the profile is a personalised-range volume profile on the chart (SCR-038 is also a chart overlay)
- the pending range end (DE-08, W-25) is drawn with a dashed vertical and the word "pending"; the profile rows keep the applied range until Enter

## G rows (0)

## C rows (2)

- D09-C6 (§19.1 L399): E14-D02 stands on drawing surrogates; ×100 is not offered there
- D09-C7 (§19.1 L400): E14-D02 stands: Esc keeps the applied nudge (W-18); Ctrl+Z is the drawing's cancel (K-5)

## Spec gaps (0)

## Deviations (0)

## Copy keys (2)

- W-18 (§16 L323, PROPOSED (an applied-at-once object, K-5))
- W-25 (§16 L330, PROPOSED (a pending local object: DE-08, DE-10, DE-19))

## Copy gaps (2)

- SCR-063 column words "Order", "Symbol", "Side", "Qty", "Price", "Status" and the row words "Position", "Stop-loss", "Take-profit", "Open", "Working": the grid's own (`14`:1523), not this spec's
- "Edit values…" popover words "Anchors", "Anchor 1", "Anchor 2", "Time", "Price" and the title: E14-D02 §7.1's anchor field pairs (D02E14 §7.1) name no copy; the other popover fields are placeholders

## Fallbacks (6)

- kit choice: the chart is drawn at 4 px per tick and 12 px per 1-minute bar; candles, axis labels and the profile are derived from the seeded series (every label = a price on the tick grid)
- kit choice: numbered stop markers, tags, outlines, arrows and callouts are annotation overlays in color.status.info.default (callouts on color.surface.overlay), never product UI; a callout quotes what is spoken (polite) or what a key does
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); SCR-012's rows 32 px (E10-D03 §6.1, D03E10:281: 32 compact, 40 comfortable); the shell bars keep E10's 48 px TopBar
- fallback (E47-D04's): border.panel.focus (= {border.focus}, `16`:88) is not in the token file: the focused panel's inset frame is a border.focus inner stroke in color.focus.ring and its header bar a 3 px color.focus.ring rect
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items, list rows of SCR-093) drawn as neutral placeholders; only what this spec names is drawn with words
- fallback: the renderer draws no dashed stroke: the pending line is 8 px segments with 4 px gaps of the line's own token (each segment a rect), always with its "pending" label (§13: never colour or a line style alone)

## Sources (1)

- spec docs/design/E47/E47-D09.md md5 690029fa (§0 L70); hand-off docs/design/E47/E47-D09-handoff.md md5 d50c31f7 (§H L105); registry at 4c662fd5b apps/web/src/keymap/keymap.json md5 eb409e85 and apps/web/src/keymap/reserved-keys.json md5 5683c37f; tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (54)

- color.drawing.selected
- border.thick
- radius.control
- color.surface.canvas
- border.hairline
- color.focus.ring
- border.focus
- type.num.xs
- color.text.primary
- space.inset.xs
- color.surface.raised
- color.border.default
- color.position.entry
- color.position.tp
- color.position.sl
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
- color.surface.hover
- space.inset.md
- color.surface.selected
- color.surface.app
- color.env.live
- space.button.paddingX
- color.status.danger.subtle
- color.status.danger.strong
- space.inset.lg
- type.ui.heading-sm
- color.action.secondary.default
- color.border.strong
- space.stack.sm
- radius.card
- color.profile.valuearea
- color.profile.poc
- color.profile.bar
- color.drawing.default
- color.text.tertiary
