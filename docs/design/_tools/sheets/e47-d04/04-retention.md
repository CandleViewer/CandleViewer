# E47-D04 / 04 retention

File `E47-D04 boards`, page `E47-D04 — Focus model`; export `docs/design/E47/img/E47-D04-04-retention.png`; sheet `04-retention.json` (validated); theme dark.

Board 04 of ten (§0 L74: a re-seed: the level kept, the nearest level with its label (W-4); a closed position's successor (W-5); 2.4.11 under a floating ticket). Grid (18000, 0); 3280 x 1878 px; "page E47-D04 — Focus model · board 04 · r1".

## Frames

- `retention∕level-kept · dark`
- `retention∕nearest · dark`
- `retention∕row-removed · dark`
- `retention∕not-obscured · dark`

## Validator and size

- `04-retention.json: 0 errors, 1 warnings, 76 sections, 209879 bytes` (exit 0)
- 76 sections, 209879 bytes

## Live checks (7)

- root 'E47-D04 / 04 retention' at (18000, 0): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 1009 px) ends inside the root (h 1878); set the root's h to max(column end, footer end) + 80
- frame 'retention∕level-kept · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'retention∕nearest · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'retention∕row-removed · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'retention∕not-obscured · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E47/img/E47-D04-04-retention.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (1)

- D04-G3 (§18.2 L457): no layout query returns the rectangles that overlap a scroll container, which R-11 needs

## Spec gaps (0)

## Deviations (0)

## Copy keys (2)

- W-4 (§15 L380, PROPOSED, the nearest-level move (§8))
- W-5 (§15 L381, PROPOSED, the removed-row move (§8))

## Copy gaps (0)

## Fallbacks (4)

- kit choice: numbered stop markers, region tags and move arrows are annotation overlays in color.status.info.default on color.text.inverse, never product UI
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items) drawn as neutral placeholders; only what the focus model names is drawn with words
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); the shell bars keep E10's 48 px TopBar
- fallback: border.panel.focus (= {border.focus}, `16`:88) is not in the token file: the inset panel frame is drawn as a border.focus inner stroke in color.focus.ring; the header bar as a 3 px color.focus.ring rect (border.thick + border.hairline, the `16`:88 composite)

## Sources (1)

- spec E47-D04.md md5 82406120 (§0 L74); hand-off E47-D04-handoff.md md5 d6454712 (§H L94); tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (37)

- type.ui.label
- color.text.primary
- type.ui.caption
- space.stack.xs
- space.inset.sm
- color.surface.overlay
- radius.control
- color.status.info.default
- border.thick
- space.inset.xs
- type.num.base
- color.surface.canvas
- color.surface.raised
- border.hairline
- color.focus.ring
- border.focus
- color.text.secondary
- color.border.default
- color.surface.hover
- type.ui.body
- space.stack.sm
- space.inset.md
- size.icon
- type.ui.body-strong
- color.surface.selected
- color.surface.app
- color.border.subtle
- color.env.live
- space.button.paddingX
- color.status.danger.subtle
- color.status.danger.strong
- space.inset.lg
- radius.card
- color.border.strong
- color.text.inverse
- type.ui.heading-sm
- color.text.tertiary
