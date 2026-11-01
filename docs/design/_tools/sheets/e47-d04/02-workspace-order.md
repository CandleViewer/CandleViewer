# E47-D04 / 02 workspace-order

File `E47-D04 boards`, page `E47-D04 — Focus model`; export `docs/design/E47/img/E47-D04-02-workspace-order.png`; sheet `02-workspace-order.json` (validated); theme dark.

Board 02 of ten (§0 L72: the workspace archetype's Tab sequence and roving zones over a four-panel layout, the panel header bar and frame (§4)). Grid (6000, 0); 3280 x 998 px; "page E47-D04 — Focus model · board 02 · r1".

## Frames

- `workspace∕tab-sequence · dark`
- `workspace∕roving-zones · dark`

## Validator and size

- `02-workspace-order.json: 0 errors, 1 warnings, 63 sections, 115890 bytes` (exit 0)
- 63 sections, 115890 bytes

## Live checks (5)

- root 'E47-D04 / 02 workspace-order' at (6000, 0): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the annotation column (estimated 900 px) ends inside the root (h 998); set the root's h to max(column end, footer end) + 80
- frame 'workspace∕tab-sequence · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'workspace∕roving-zones · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D04-02-workspace-order.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (4)

- kit choice: numbered stop markers, region tags and move arrows are annotation overlays in color.status.info.default on color.text.inverse, never product UI
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items) drawn as neutral placeholders; only what the focus model names is drawn with words
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); the shell bars keep E10's 48 px TopBar
- fallback: border.panel.focus (= {border.focus}, `16`:88) is not in the token file: the inset panel frame is drawn as a border.focus inner stroke in color.focus.ring; the header bar as a 3 px color.focus.ring rect (border.thick + border.hairline, the `16`:88 composite)

## Sources (1)

- spec E47-D04.md md5 ec4172fe (§0 L72); hand-off E47-D04-handoff.md md5 7ffe0dc8 (§H L94); tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (36)

- type.ui.label
- color.text.inverse
- color.status.info.default
- radius.badge
- type.ui.caption
- space.inset.xs
- radius.control
- color.text.primary
- space.stack.xs
- space.inset.sm
- color.surface.overlay
- border.thick
- color.surface.hover
- type.num.base
- color.surface.canvas
- color.surface.raised
- color.text.secondary
- color.border.default
- type.ui.body
- space.stack.sm
- space.inset.md
- size.icon
- border.hairline
- color.focus.ring
- border.focus
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
