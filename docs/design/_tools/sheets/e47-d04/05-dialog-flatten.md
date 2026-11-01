# E47-D04 / 05 dialog-flatten

File `E47-D04 boards`, page `E47-D04 — Focus model`; export `docs/design/E47/img/E47-D04-05-dialog-flatten.png`; sheet `05-dialog-flatten.json` (validated); theme dark.

Board 05 of ten (§0 L75: the flatten-all ConfirmDialog: trap, Cancel initial, restore to the TopBar control on Esc and on completion (§9)). Grid (24000, 0); 3280 x 998 px; "page E47-D04 — Focus model · board 05 · r1".

## Frames

- `dialog∕flatten-open · dark`
- `dialog∕flatten-restore · dark`

## Validator and size

- `05-dialog-flatten.json: 0 errors, 2 warnings, 35 sections, 106247 bytes` (exit 0)
- 35 sections, 106247 bytes

## Live checks (6)

- modal: re-centre 'CMP-044 alertdialog · flatten all' after relayout (estimated 480 x 187 px)
- root 'E47-D04 / 05 dialog-flatten' at (24000, 0): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the annotation column (estimated 824 px) ends inside the root (h 998); set the root's h to max(column end, footer end) + 80
- frame 'dialog∕flatten-open · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'dialog∕flatten-restore · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D04-05-dialog-flatten.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (0)

## Spec gaps (0)

## Deviations (1)

- dialog width 480 px: a kit choice (no source gives CMP-044's width)

## Copy keys (0)

## Copy gaps (1)

- dialog title "Flatten all positions — all accounts": E39-D03 §10 S1 (the FLATTEN ALL control's accessible name); E47-D04 names the dialog only as "the flatten-all ConfirmDialog" (§0) and E39-D01 owns its copy

## Fallbacks (4)

- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items) drawn as neutral placeholders; only what the focus model names is drawn with words
- fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim
- kit choice: numbered stop markers, region tags and move arrows are annotation overlays in color.status.info.default on color.text.inverse, never product UI
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); the shell bars keep E10's 48 px TopBar

## Sources (1)

- spec E47-D04.md md5 ec4172fe (§0 L75); hand-off E47-D04-handoff.md md5 7ffe0dc8 (§H L94); tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (43)

- radius.control
- color.surface.hover
- type.ui.body-strong
- color.text.primary
- space.inset.xs
- space.button.paddingX
- color.action.secondary.default
- color.surface.canvas
- border.hairline
- color.focus.ring
- border.focus
- color.status.danger.subtle
- color.status.danger.strong
- space.stack.sm
- type.ui.heading-md
- space.inset.sm
- color.surface.overlay
- radius.dialog
- space.dialog.padding
- space.stack.md
- color.border.default
- opacity.scrim
- color.surface.sunken
- type.ui.label
- color.text.inverse
- color.status.info.default
- radius.badge
- type.ui.caption
- type.num.base
- color.surface.raised
- color.text.secondary
- space.stack.xs
- type.ui.body
- space.inset.md
- size.icon
- color.surface.selected
- color.surface.app
- color.border.subtle
- color.env.live
- space.inset.lg
- border.thick
- type.ui.heading-sm
- color.text.tertiary
