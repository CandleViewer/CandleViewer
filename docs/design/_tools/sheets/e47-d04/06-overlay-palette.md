# E47-D04 / 06 overlay-palette

File `E47-D04 boards`, page `E47-D04 — Focus model`; export `docs/design/E47/img/E47-D04-06-overlay-palette.png`; sheet `06-overlay-palette.json` (validated); theme dark.

Board 06 of ten (§0 L76: SCR-012 and SCR-013: the field and the list stop, Esc restore, a menu's Tab-out (§4, §9)). Grid (0, 3200); 4640 x 1101 px; "page E47-D04 — Focus model · board 06 · r1".

## Frames

- `overlay∕palette · dark`
- `overlay∕cheatsheet · dark`
- `overlay∕menu-tab-out · dark`

## Validator and size

- `06-overlay-palette.json: 0 errors, 3 warnings, 55 sections, 162415 bytes` (exit 0)
- 55 sections, 162415 bytes

## Live checks (8)

- modal: re-centre 'CMP-059 command palette' after relayout (estimated 560 x 185 px)
- modal: re-centre 'CMP-094 hotkey overlay' after relayout (estimated 744 x 282 px)
- root 'E47-D04 / 06 overlay-palette' at (0, 3200): read back the name exactly after the first section call; size 4640 x 1101
- after touchTexts + relayout: the annotation column (estimated 1004 px) ends inside the root (h 1101); set the root's h to max(column end, footer end) + 80
- frame 'overlay∕palette · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'overlay∕cheatsheet · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'overlay∕menu-tab-out · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D04-06-overlay-palette.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (1)

- W-6 (§15 L382, PROPOSED, the overlay result count)

## Copy gaps (1)

- "Hotkey cheatsheet", "Search hotkeys" and the action words: `14` SCR-013 / SCR-010 (L376, L302 of 14) and §3 / §6; the bindings themselves are E47-D09's (#1308)

## Fallbacks (5)

- fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim
- kit choice: numbered stop markers, region tags and move arrows are annotation overlays in color.status.info.default on color.text.inverse, never product UI
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items) drawn as neutral placeholders; only what the focus model names is drawn with words
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); the shell bars keep E10's 48 px TopBar
- fallback: border.panel.focus (= {border.focus}, `16`:88) is not in the token file: the inset panel frame is drawn as a border.focus inner stroke in color.focus.ring; the header bar as a 3 px color.focus.ring rect (border.thick + border.hairline, the `16`:88 composite)

## Sources (1)

- spec E47-D04.md md5 ec4172fe (§0 L76); hand-off E47-D04-handoff.md md5 7ffe0dc8 (§H L94); tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (43)

- type.ui.body
- color.text.primary
- space.inset.sm
- color.surface.selected
- color.text.secondary
- size.icon
- space.inset.xs
- color.surface.canvas
- radius.control
- color.border.default
- border.hairline
- color.focus.ring
- border.focus
- type.ui.caption
- space.stack.sm
- space.inset.md
- color.surface.overlay
- radius.dialog
- opacity.scrim
- color.surface.sunken
- type.ui.label
- color.text.inverse
- color.status.info.default
- radius.badge
- space.stack.xs
- border.thick
- color.surface.hover
- type.num.base
- color.surface.raised
- type.ui.body-strong
- color.surface.app
- color.border.subtle
- color.env.live
- space.button.paddingX
- color.status.danger.subtle
- color.status.danger.strong
- space.inset.lg
- type.ui.heading-md
- space.stack.md
- space.dialog.padding
- radius.card
- type.ui.heading-sm
- color.text.tertiary
