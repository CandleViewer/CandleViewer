# E47-D04 / 07 full-page-form

File `E47-D04 boards`, page `E47-D04 — Focus model`; export `docs/design/E47/img/E47-D04-07-full-page-form.png`; sheet `07-full-page-form.json` (validated); theme dark.

Board 07 of ten (§0 L77: SCR-110 with SCR-117, and SCR-121: the page sequence, the h1 on entry, a T2 control in the order, a T3 item absent (§4, §10)). Grid (6000, 3200); 3280 x 1042 px; "page E47-D04 — Focus model · board 07 · r1".

## Frames

- `form∕settings-sequence · dark`
- `form∕admin-t2-t3 · dark`

## Validator and size

- `07-full-page-form.json: 0 errors, 0 warnings, 32 sections, 52564 bytes` (exit 0)
- 32 sections, 52564 bytes

## Live checks (5)

- root 'E47-D04 / 07 full-page-form' at (6000, 3200): read back the name exactly after the first section call; size 3280 x 1042
- after touchTexts + relayout: the annotation column (estimated 974 px) ends inside the root (h 1042); set the root's h to max(column end, footer end) + 80
- frame 'form∕settings-sequence · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'form∕admin-t2-t3 · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D04-07-full-page-form.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (2)

- W-7 (§15 L383, verbatim (the shipped label))
- W-8 (§15 L384, verbatim (the shipped help))

## Copy gaps (1)

- T2 reason "Only the owner can flatten every account.": E39-D03 §10 S4 (the global FLATTEN ALL for a Manager; E09-D09 rbac.owner_only)

## Fallbacks (3)

- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items) drawn as neutral placeholders; only what the focus model names is drawn with words
- kit choice: numbered stop markers, region tags and move arrows are annotation overlays in color.status.info.default on color.text.inverse, never product UI
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); the shell bars keep E10's 48 px TopBar

## Sources (1)

- spec E47-D04.md md5 82406120 (§0 L77); hand-off E47-D04-handoff.md md5 d6454712 (§H L94); tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (38)

- type.ui.body
- color.text.primary
- space.inset.sm
- radius.control
- color.surface.selected
- type.ui.label
- color.text.secondary
- space.stack.xs
- color.surface.raised
- type.ui.heading-lg
- color.surface.hover
- radius.badge
- color.border.default
- border.hairline
- type.ui.body-strong
- space.inset.md
- type.ui.caption
- color.surface.canvas
- color.focus.ring
- border.focus
- type.ui.heading-md
- space.stack.lg
- color.surface.app
- color.text.inverse
- color.status.info.default
- space.inset.xs
- color.border.subtle
- color.env.live
- space.button.paddingX
- color.status.danger.subtle
- color.status.danger.strong
- space.inset.lg
- color.text.tertiary
- size.icon
- color.surface.overlay
- border.thick
- type.ui.heading-sm
- space.stack.sm
