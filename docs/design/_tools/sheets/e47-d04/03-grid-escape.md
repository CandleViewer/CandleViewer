# E47-D04 / 03 grid-escape

File `E47-D04 boards`, page `E47-D04 — Focus model`; export `docs/design/E47/img/E47-D04-03-grid-escape.png`; sheet `03-grid-escape.json` (validated); theme dark.

Board 03 of ten (§0 L73: the DOM ladder as one stop: entry with its extent label (W-2), Tab out, the Esc layers to the panel header (§6)). Grid (12000, 0); 4640 x 1036 px; "page E47-D04 — Focus model · board 03 · r1".

## Frames

- `grid∕entry · dark`
- `grid∕tab-out · dark`
- `grid∕esc-layers · dark`

## Validator and size

- `03-grid-escape.json: 0 errors, 1 warnings, 58 sections, 154104 bytes` (exit 0)
- 58 sections, 154104 bytes

## Live checks (6)

- root 'E47-D04 / 03 grid-escape' at (12000, 0): read back the name exactly after the first section call; size 4640 x 1036
- after touchTexts + relayout: the annotation column (estimated 978 px) ends inside the root (h 1036); set the root's h to max(column end, footer end) + 80
- frame 'grid∕entry · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'grid∕tab-out · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'grid∕esc-layers · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D04-03-grid-escape.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (1)

- W-2 (§15 L378, verbatim (T Scope))

## Copy gaps (0)

## Fallbacks (4)

- kit choice: numbered stop markers, region tags and move arrows are annotation overlays in color.status.info.default on color.text.inverse, never product UI
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items) drawn as neutral placeholders; only what the focus model names is drawn with words
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); the shell bars keep E10's 48 px TopBar
- fallback: border.panel.focus (= {border.focus}, `16`:88) is not in the token file: the inset panel frame is drawn as a border.focus inner stroke in color.focus.ring; the header bar as a 3 px color.focus.ring rect (border.thick + border.hairline, the `16`:88 composite)

## Sources (1)

- spec E47-D04.md md5 82406120 (§0 L73); hand-off E47-D04-handoff.md md5 d6454712 (§H L94); tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (36)

- type.ui.label
- color.text.inverse
- color.status.info.default
- radius.badge
- color.text.primary
- type.ui.caption
- space.stack.xs
- space.inset.sm
- color.surface.overlay
- radius.control
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
- type.ui.heading-sm
- color.text.tertiary
