# E47-D04 / 01 landmarks-ring

File `E47-D04 boards`, page `E47-D04 — Focus model`; export `docs/design/E47/img/E47-D04-01-landmarks-ring.png`; sheet `01-landmarks-ring.json` (validated); theme dark.

Board 01 of ten (§0 L71: SCR-020: the landmarks (§2), every region numbered in ring order, the wrap arrow, SR-04's label at one arrival (§3)). Grid (0, 0); 3280 x 998 px; "page E47-D04 — Focus model · board 01 · r1".

## Frames

- `shell∕landmarks · dark`
- `shell∕ring-order · dark`

## Validator and size

- `01-landmarks-ring.json: 0 errors, 1 warnings, 61 sections, 112482 bytes` (exit 0)
- 61 sections, 112482 bytes

## Live checks (5)

- root 'E47-D04 / 01 landmarks-ring' at (0, 0): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the annotation column (estimated 890 px) ends inside the root (h 998); set the root's h to max(column end, footer end) + 80
- frame 'shell∕landmarks · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'shell∕ring-order · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D04-01-landmarks-ring.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (1)

- D04-G4 (§18.2 L458): no ordered region list is exposed by the layout system for the ring (T Tech)

## Spec gaps (0)

## Deviations (0)

## Copy keys (1)

- W-1 (§15 L377, verbatim (SR-04))

## Copy gaps (0)

## Fallbacks (4)

- kit choice: numbered stop markers, region tags and move arrows are annotation overlays in color.status.info.default on color.text.inverse, never product UI
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items) drawn as neutral placeholders; only what the focus model names is drawn with words
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); the shell bars keep E10's 48 px TopBar
- fallback: border.panel.focus (= {border.focus}, `16`:88) is not in the token file: the inset panel frame is drawn as a border.focus inner stroke in color.focus.ring; the header bar as a 3 px color.focus.ring rect (border.thick + border.hairline, the `16`:88 composite)

## Sources (1)

- spec E47-D04.md md5 ec4172fe (§0 L71); hand-off E47-D04-handoff.md md5 7ffe0dc8 (§H L94); tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (36)

- color.status.info.default
- border.thick
- type.ui.caption
- color.text.inverse
- space.inset.xs
- radius.control
- color.surface.hover
- space.inset.sm
- type.num.base
- color.text.primary
- color.surface.canvas
- color.surface.raised
- color.text.secondary
- color.border.default
- space.stack.xs
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
- border.hairline
- space.inset.lg
- type.ui.label
- radius.badge
- color.surface.overlay
- color.focus.ring
- border.focus
- type.ui.heading-sm
- color.text.tertiary
